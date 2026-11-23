import logging
import os
from threading import Lock

from flask import Flask, jsonify, render_template, request

from gemini_api import GeminiClient
from reading_workflow import ReadingWorkflow, WorkflowError
from tavily_api import TavilySearcher


def create_app(workflow):
    app = Flask(__name__)

    operation_lock = Lock()

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/state")
    def state():
        if not operation_lock.acquire(blocking=False):
            return jsonify(
                error="진행 중인 작업이 있습니다. 잠시 후 새로고침해주세요."
            ), 409

        try:
            return jsonify(state=workflow.snapshot())
        finally:
            operation_lock.release()

    @app.post("/api/action")
    def action():
        if not request.is_json:
            return jsonify(error="JSON 요청이 필요합니다."), 415

        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(error="요청 형식이 올바르지 않습니다."), 400

        if not operation_lock.acquire(blocking=False):
            return jsonify(error="이미 작업을 진행하고 있습니다."), 409

        try:
            command = body.get("action")

            if command == "start":
                workflow.start()

            # 사용자가 제시된 기사 중 하나를 선택하는 경우.
            elif command == "select_article":
                workflow.select_article(body.get("index"))

            # 사용자가 답변 후 제출하는 경우 or
            # 추가 질문에 대한 답변 제출하는 경우.
            elif command == "submit":
                workflow.submit_answers(body.get("answers"))

            elif command == "retry":
                workflow.retry_evaluation()

            # 사용자가 문제를 해결하고 다음 주제를 요청한 경우.
            elif command == "next":
                workflow.next_article(
                    topic_index=body.get("topic_index"),
                    interest=body.get("interest"),
                )
            else:
                raise WorkflowError("지원하지 않는 작업입니다.")

            return jsonify(state=workflow.snapshot())

        except WorkflowError as exc:
            return jsonify(
                error=str(exc),
                state=workflow.snapshot(),
            ), 400

        except Exception:
            app.logger.exception("학습 처리 중 오류")
            return jsonify(
                error="처리 중 오류가 발생했습니다. 다시 시도해주세요.",
                state=workflow.snapshot(),
            ), 500

        finally:
            operation_lock.release()

    return app


def main():
    logging.basicConfig(level=logging.INFO)

    model_name = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    tavily_api_key = os.getenv("TAVILY_API_KEY")

    if not gemini_api_key:
        raise ValueError("GEMINI_API_KEY 환경변수가 필요합니다.")

    if not tavily_api_key:
        raise ValueError("TAVILY_API_KEY 환경변수가 필요합니다.")


    workflow = ReadingWorkflow(
        gemini=GeminiClient(
            api_key=gemini_api_key,
            model_name=model_name,
        ),
        searcher=TavilySearcher(
            api_key=tavily_api_key,
            max_results=3,
        ),
        evaluation_attempts=2,
        max_follow_up_rounds=10,
    )

    app = create_app(workflow)
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        threaded=True,
    )


if __name__ == "__main__":
    main()
