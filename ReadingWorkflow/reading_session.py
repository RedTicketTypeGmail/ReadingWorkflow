from dataclasses import dataclass, field
from typing import Literal


QuestionStatus = Literal["pending", "correct", "wrong"]

@dataclass
class FollowUpAnswer:
    question: str
    answer: str

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "answer": self.answer,
        }


@dataclass
class ReadingQuestion:
    question_id: str
    text: str
    question_type: str

    model_answer: str
    answer: str | None = None

    status: QuestionStatus = "pending"

    follow_up_question: str | None = None

    follow_up_history: list[FollowUpAnswer] = field(
        default_factory=list
    )

    def submit_answer(self, answer: str) -> None:
        answer = answer.strip()

        if not answer:
            raise ValueError("답변은 비워둘 수 없습니다.")

        if self.answer is not None:
            raise ValueError("이미 최초 답변이 등록된 문제입니다.")

        self.answer = answer

    def submit_follow_up_answer(self, answer: str) -> None:
        answer = answer.strip()

        if not answer:
            raise ValueError("답변은 비워둘 수 없습니다.")

        if not self.needs_follow_up():
            raise ValueError("답변할 추가 질문이 없습니다.")

        self.follow_up_history.append(
            FollowUpAnswer(
                question=self.follow_up_question,
                answer=answer,
            )
        )

        self.follow_up_question = None


    def needs_follow_up(self) -> bool:
        return (
            self.status == "wrong"
            and bool(self.follow_up_question)
        )

    def to_evaluation_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "text": self.text,
            "type": self.question_type,
            "model_answer": self.model_answer,
            "answer": self.answer,
            "status": self.status,
            "follow_up_question": self.follow_up_question,
            "follow_up_history": [
                record.to_dict()
                for record in self.follow_up_history
            ],
        }


class ReadingSession:
    def __init__(self, article: dict):
        article_data = article["article"]

        self.title = article_data["title"]
        self.text = article_data["text"]
        self.translation = article_data["translation"]
        self.url = article_data.get("url", "")
        self.published_date = article_data.get("published_date")

        self.tmi = article["tmi"]
        self.related_topics = article["related_topic"]

        self.questions = [
            ReadingQuestion(
                question_id=f"q{index + 1}",
                text=question["text"],
                question_type=question["type"],
                model_answer=question["answer"],
            )
            for index, question in enumerate(article["question"])
        ]

    @property
    def is_complete(self) -> bool:
        return bool(self.questions) and all(
            question.status == "correct"
            for question in self.questions
        )

    def pending_questions(self) -> list[tuple[int, ReadingQuestion]]:
        return [
            (index, question)
            for index, question in enumerate(self.questions)
            if question.needs_follow_up()
        ]

    def article_dict(self) -> dict:
        """다음 주제 생성에 필요한 기사 정보."""
        return {
            "title": self.title,
            "text": self.text
        }


    def to_evaluation_dict(self) -> dict:
        if any(
            question.answer is None
            for question in self.questions
        ):
            raise ValueError("모든 문제에 최초 답변이 필요합니다.")

        return {
            "title": self.title,
            "text": self.text,
            "questions": [
                question.to_evaluation_dict()
                for question in self.questions
            ],
        }

    def apply_evaluation(self, evaluations: list) -> None:
        if not isinstance(evaluations, list):
            print(evaluations)
            raise ValueError("evaluations는 리스트여야 합니다.")

        questions_by_id = {
            question.question_id: question
            for question in self.questions
        }

        validated = {}

        for evaluation in evaluations:
            question_id = evaluation.get("question_id")

            if not isinstance(question_id, str):
                raise ValueError("question_id는 문자열이어야 합니다.")

            if question_id not in questions_by_id:
                raise ValueError(
                    f"알 수 없는 문제 ID입니다: {question_id}"
                )

            if question_id in validated:
                raise ValueError(
                    f"문제 ID가 중복되었습니다: {question_id}"
                )

            status = evaluation.get("status")

            if status not in ("correct", "wrong"):
                raise ValueError(
                    f"{question_id}: 잘못된 평가 상태입니다."
                )

            if "follow_up_question" not in evaluation:
                raise ValueError(
                    f"{question_id}: 추가 질문 필드가 없습니다."
                )

            follow_up = evaluation["follow_up_question"]
            question = questions_by_id[question_id]

            
            validated[question_id] = (status, follow_up)

        for question_id, (status, follow_up) in validated.items():
            question = questions_by_id[question_id]
            question.status = status
            question.follow_up_question = follow_up           