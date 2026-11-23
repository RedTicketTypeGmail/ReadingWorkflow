import json
import logging

from google import genai
from google.genai import errors, types

from prompts import *

logger = logging.getLogger(__name__)


class GeminiClient:
    def __init__(self, api_key: str, model_name: str):
        if not api_key:
            raise ValueError("Gemini API 설정이 필요합니다.")

        if not model_name.strip():
            raise ValueError("Gemini 모델 이름이 필요합니다.")

        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name.strip()

    def request(self, prompt: str) -> dict | None:
        """모델의 JSON 객체 응답을 반환한다."""
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )

            raw_text = response.text or ""
            result = json.loads(raw_text)

            return result

        except json.JSONDecodeError:
            logger.warning("Gemini JSON 파싱 실패")
            return None

        except errors.APIError as exc:
            logger.warning(
                "Gemini API 오류: HTTP %s",
                exc,
            )
            return None

        except Exception as exc:
            logger.warning(
                "Gemini 요청 처리 실패: %s",
                exc,
            )
            return None

 
    def verify_if_article(self, articles: list):
        return self.request(verify_if_article_prompt(articles))   

    def recommend_related_articles(self, before_article: dict, related_topic: dict, search_infos: list[dict]) -> dict | None:
        if not search_infos:
            return None

        # 기사 내용 반환.
        new_article = self.request(
            recommend_related_article_prompt(
                search_infos=search_infos,
                before_article=before_article,
                related_topic=related_topic,
            )
        )

        if new_article is None:
            return None

        if new_article.get("status") == "not_found":
            logger.warning("조건에 맞는 학습 기사를 찾지 못했습니다.")
            return None

        return new_article

    def generate_related_topic(self, article: dict, user_interest: str,) -> dict | None:

        related_topic = self.request(
            generate_related_topic_prompt(article, user_interest)
        )

        if related_topic is None:
            return None

        return related_topic

    def evaluate_answers(self, reading_session: dict) -> list | None:
        return self.request(
            evaluate_answer_prompt(reading_session)
        )

    def generate_questions(self, article: dict) -> list | None:
        return self.request(generate_questions_prompt(article))