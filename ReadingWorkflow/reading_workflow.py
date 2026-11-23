from copy import deepcopy

from gemini_api import GeminiClient
from reading_session import ReadingSession
from tavily_api import TavilySearcher


class WorkflowError(Exception):
    """화면에 표시할 수 있는 학습 진행 오류."""


class ReadingWorkflow:
    CATEGORIES = ["기술", "사회", "경제", "스포츠", "반도체", "인공지능"]

    def __init__(
        self,
        gemini: GeminiClient,
        searcher: TavilySearcher,
        evaluation_attempts: int = 2,
        max_follow_up_rounds: int = 10
    ):
        if evaluation_attempts < 1 or max_follow_up_rounds < 0:
            raise ValueError("평가 횟수와 추가 질문 한도를 확인해주세요.")

        self.gemini = gemini
        self.searcher = searcher

        self.evaluation_attempts = evaluation_attempts
        self.max_follow_up_rounds = max_follow_up_rounds

        self.phase = "idle"
        self.articles = []
        self.session = None
        self.follow_up_round = 0

    # 각 주제별 기사 검색해서 객체 내 저장. 
    def start(self):
        articles = self.searcher.search_latest_articles(self.CATEGORIES)
        if not articles:
            raise WorkflowError("검색된 기사가 없습니다. 다시 시도해주세요.")

        filtered = self.gemini.verify_if_article(articles)

        if not isinstance(filtered, list):
            raise WorkflowError("기사 목록 응답 형식이 올바르지 않습니다.")

        usable = [
            item for item in filtered
            if isinstance(item, dict)
            and isinstance(item.get("title"), str)
            and item["title"].strip()
        ]

        if not usable:
            raise WorkflowError("학습할 수 있는 기사를 찾지 못했습니다.")

        self.articles = usable
        self.session = None
        self.follow_up_round = 0
        self.phase = "selecting"


    def select_article(self, index):
        self._require_phase("selecting")

        article = self._select(self.articles, index)

        content = self.gemini.generate_questions(article)

        self._load_article(content)



    def submit_answers(self, answers):
        self._require_phase("answering", "followup")

        if self.phase == "answering":
            targets = self.session.questions
        else:
            targets = [
                question
                for _, question in self.session.pending_questions()
            ]

        if not targets:
            raise WorkflowError("현재 답변할 문제가 없습니다.")

        if not isinstance(answers, dict):
            raise WorkflowError("답변 형식이 올바르지 않습니다.")

        cleaned = {}

        # 모든 입력을 검사한 뒤 실제 상태를 변경합니다.
        for question in targets:
            value = answers.get(question.question_id)

            if not isinstance(value, str) or not value.strip():
                raise WorkflowError("모든 문제에 답변을 입력해주세요.")

            cleaned[question.question_id] = value.strip()

        if self.phase == "answering":
            for question in targets:
                question.submit_answer(cleaned[question.question_id])
        else:
            for question in targets:
                question.submit_follow_up_answer(
                    cleaned[question.question_id]
                )

            self.follow_up_round += 1

        # 평가 실패 시 답변을 다시 제출하지 않고 평가만 재시도.
        self.phase = "evaluation_failed"
        self._evaluate()

    def retry_evaluation(self):
        self._require_phase("evaluation_failed")
        self._evaluate()

    def next_article(self, topic_index=None, interest=None):
        self._require_phase("completed")

        if topic_index is not None:
            selected = self._select(
                self.session.related_topics,
                topic_index,
            )
        else:
            if not isinstance(interest, str) or not interest.strip():
                raise WorkflowError("궁금한 주제를 입력해주세요.")

            selected = self.gemini.generate_related_topic(
                self.session.article_dict(),
                interest.strip(),
            )

        if (
            not isinstance(selected, dict)
            or not isinstance(selected.get("search_query"), str)
            or not selected["search_query"].strip()
        ):
            raise WorkflowError("검색 가능한 관련 주제를 만들지 못했습니다.")

        results = self.searcher.search_related_articles(
            selected["search_query"]
        )

        if not results:
            raise WorkflowError(
                "기사 본문을 확보하지 못했습니다. 다른 주제를 선택해주세요."
            )

        content = self.gemini.recommend_related_articles(
            before_article=self.session.article_dict(),
            related_topic=selected,
            search_infos=results,
        )

        # 생성에 실패하면 완료된 기존 학습을 그대로 유지.
        self._load_article(content)


    # 받은 content 를 현재 WorkFlow 가 처리해야할 session 으로 등록하고, phase 를 answering 으로 변환.
    def _load_article(self, content):
        if not isinstance(content, dict):
            raise WorkflowError("학습 자료를 생성하지 못했습니다.")

        try:
            session = ReadingSession(content)

            for value in (
                session.title,
                session.text,
                session.translation,
            ):
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("기사 내용 누락")

            if not session.questions:
                raise ValueError("기사 내 문제가 없음")

            for question in session.questions:
                for value in (
                    question.text,
                    question.question_type,
                    question.model_answer,
                ):
                    if not isinstance(value, str) or not value.strip():
                        raise ValueError("문제 내용 누락")

            for items, fields in (
                (session.tmi, ("title", "content")),
                (
                    session.related_topics,
                    ("topic", "connection", "summary", "search_query"),
                ),
            ):
                if not isinstance(items, list):
                    raise ValueError("목록 형식 오류")

                for item in items:
                    if not isinstance(item, dict):
                        raise ValueError("항목 형식 오류")

                    if any(
                        not isinstance(item.get(key), str)
                        or not item[key].strip()
                        for key in fields
                    ):
                        raise ValueError("항목 내용 누락")

        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise WorkflowError(
                "학습 자료에 필수 정보가 빠져 있습니다. 다시 시도해주세요."
            ) from exc

        self.session = session
        self.follow_up_round = 0
        self.phase = "answering"

    def _evaluate(self):
        payload = self.session.to_evaluation_dict()
        
        for _ in range(self.evaluation_attempts):
            result = self.gemini.evaluate_answers(deepcopy(payload))
            print(result)
            try:
                self._validate_evaluations(result)
                self.session.apply_evaluation(result)
            except ValueError:
                continue

            if self.session.is_complete:
                self.phase = "completed"
            elif self.follow_up_round >= self.max_follow_up_rounds:
                self.phase = "stopped"
            else:
                self.phase = "followup"
            return

        raise WorkflowError(
            "답변은 저장했지만 평가에 실패했습니다. 평가를 재시도해주세요."
        )

    def _validate_evaluations(self, evaluations):
        if not isinstance(evaluations, list):
            raise ValueError("평가는 리스트여야 합니다.")

        expected = {
            question.question_id: question
            for question in self.session.questions
        }
        seen = set()

        for item in evaluations:
            if not isinstance(item, dict):
                raise ValueError("평가 항목은 객체여야 합니다.")

            question_id = item.get("question_id")
            if not isinstance(question_id, str):
                raise ValueError("문제 ID 형식 오류")

            if question_id not in expected or question_id in seen:
                raise ValueError("알 수 없거나 중복된 문제 ID")

            status = item.get("status")
            if status not in ("correct", "wrong"):
                raise ValueError("평가 상태 오류")

            if "follow_up_question" not in item:
                raise ValueError("추가 질문 필드 누락")

            follow_up = item["follow_up_question"]
            if status == "wrong":
                if not isinstance(follow_up, str) or not follow_up.strip():
                    raise ValueError("오답에는 추가 질문이 필요합니다.")
                item["follow_up_question"] = follow_up.strip()
            else:
                item["follow_up_question"] = None

            # 이미 해결한 문제를 다시 오답 처리하지 않습니다.
            if expected[question_id].status == "correct":
                item["status"] = "correct"
                item["follow_up_question"] = None

            seen.add(question_id)

        if seen != set(expected):
            raise ValueError("평가되지 않은 문제가 있습니다.")

    def snapshot(self):
        """화면에 필요한 데이터만 반환합니다."""
        state = {
            "phase": self.phase,
            "follow_up_round": self.follow_up_round,
            "max_follow_up_rounds": self.max_follow_up_rounds,
            "articles": [],
            "session": None,
        }

        if self.phase == "selecting":
            state["articles"] = [
                {
                    "index": index,
                    "title": article["title"],
                    "url": article.get("url"),
                }
                for index, article in enumerate(self.articles)
            ]

        if self.session is None:
            return state

        session = self.session
        completed = self.phase == "completed"

        state["session"] = {
            "title": session.title,
            "text": session.text,
            "url": session.url,
            "correct_count": sum(
                question.status == "correct"
                for question in session.questions
            ),
            "questions": [
                {
                    "id": question.question_id,
                    "text": question.text,
                    "type": question.question_type,
                    "status": question.status,
                    "answer": question.answer,
                    "follow_up_question": question.follow_up_question,
                    "history": [
                        item.to_dict()
                        for item in question.follow_up_history
                    ],
                    # 정답은 학습 완료 전에는 브라우저로 보내지 않습니다.
                    "model_answer": (
                        question.model_answer if completed else None
                    ),
                }
                for question in session.questions
            ],
            "translation": session.translation if completed else None,
            "tmi": session.tmi if completed else [],
            "related_topics": (
                session.related_topics if completed else []
            ),
        }

        return state

    def _require_phase(self, *allowed):
        if self.phase not in allowed:
            raise WorkflowError("현재 단계에서는 사용할 수 없는 기능입니다.")

    @staticmethod
    def _select(items, index):
        if type(index) is not int or not 0 <= index < len(items):
            raise WorkflowError("목록에 있는 항목을 선택해주세요.")

        return items[index]