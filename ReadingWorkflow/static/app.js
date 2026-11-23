let state = null;
let working = false;

let drafts = {};
let interestDraft = "";

function cloneTemplate(templateId) {
    const template = document.getElementById(templateId);

    if (!(template instanceof HTMLTemplateElement)) {
        throw new Error(`화면 템플릿을 찾지 못했습니다: ${templateId}`);
    }

    return template.content.cloneNode(true);
}

function findRole(root, role) {
    return root.querySelector(`[data-role="${role}"]`);
}

function setText(root, role, value) {
    findRole(root, role).textContent = String(value != null ? value : "");
}

function safeUrl(value) {
    try {
        const url = new URL(value);
        return ["http:", "https:"].includes(url.protocol) ? url.href : "";
    } catch {
        return "";
    }
}


function showError(message) {
    notice.textContent = message;
    notice.hidden = !message;
}

function setBusy(value, message = "") {
    working = value;
    busy.hidden = !value;
    busyText.textContent = message;

    view.setAttribute("aria-busy", String(value));

    document.querySelectorAll("button, textarea, input").forEach(element => {
        element.disabled = value;
    });
}

function rememberInputs() {
    view.querySelectorAll("[data-answer]").forEach(element => {
        drafts[element.dataset.answer] = element.value;
    });

    const interest = view.querySelector("#interest");

    if (interest) {
        interestDraft = interest.value;
    }
}



async function act(action, payload = {}, message = "처리하고 있습니다...") {
    if (working) return;

    rememberInputs();
    showError("");
    setBusy(true, message);

    try {
        const response = await fetch("/api/action", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify({ ...payload, action })
        });

        const data = await response.json();

        if (data.state) {
            state = data.state;

            if (response.ok) {
                drafts = {};
                interestDraft = "";
            }

            render();
        }

        if (!response.ok) {
            throw new Error(data.error || "요청을 처리하지 못했습니다.");
        }
    } catch (error) {
        showError(error.message || "서버와 연결하지 못했습니다.");

    } finally {
        setBusy(false);
    }
}



function render() {
    if (!state) return;

    const phase = state.phase;

    const step = ["idle", "selecting"].includes(phase)
        ? 1
        : phase === "completed" ? 3 : 2;

    document.querySelectorAll("[data-step]").forEach(element => {
        element.classList.toggle(
            "active",
            Number(element.dataset.step) === step
        );
    });

    restart.hidden = phase === "idle";

    if (phase === "idle") {
        view.replaceChildren(cloneTemplate("tpl-home"));
        return;
    }

    if (phase === "selecting") {
        renderSelection();
        return;
    }

    renderSession();
}



function renderSelection() {
    const screen = cloneTemplate("tpl-selection");
    const articleList = findRole(screen, "article-list");

    for (const article of state.articles) {
        const card = cloneTemplate("tpl-article-card");
        const button = card.querySelector("button");

        button.dataset.article = String(article.index);

        setText(
            card,
            "number",
            `ARTICLE ${String(article.index + 1).padStart(2, "0")}`
        );

        setText(card, "title", article.title);
        articleList.append(card);
    }

    view.replaceChildren(screen);
}


function renderQuestion(question, index) {
    const screen = cloneTemplate("tpl-question");
    const phase = state.phase;

    const editable =
        phase === "answering" ||
        (phase === "followup" && question.status === "wrong");

    const statusLabels = {
        pending: "답변 대기",
        correct: "해결 완료",
        wrong: "한 번 더 생각하기"
    };

    setText(screen, "number", `QUESTION ${index + 1}`);
    setText(screen, "question-text", question.text);

    const badge = findRole(screen, "status");
    badge.textContent = statusLabels[question.status] != null ? statusLabels[question.status] : "상태 확인";

    badge.classList.add(
    Object.hasOwn(statusLabels, question.status)
        ? question.status
        : "pending"
    );
    

     // 최초 답변
    if (question.answer != null) {
        const answer = findRole(screen, "initial-answer");
        answer.hidden = false;
        answer.textContent = `나의 첫 답변: ${question.answer}`;
    }

    // 추가 질문 기록
    const history = question.history != null ? question.history : [];

    if (history.length > 0) {
        findRole(screen, "history").hidden = false;

        setText(
            screen,
            "history-summary",
            `추가 질문 기록 ${history.length}개`
        );

        const historyList = findRole(screen, "history-list");

        for (const record of history) {
            const item = cloneTemplate("tpl-history-item");

            setText(item, "question", `질문: ${record.question}`);
            setText(item, "answer", `답변: ${record.answer}`);

            historyList.append(item);
        }
    }

    // 현재 답변할 추가 질문
    if (phase === "followup" && question.status === "wrong") {
        const hint = findRole(screen, "followup-question");
        hint.hidden = false;
        hint.textContent = question.follow_up_question != null ? question.follow_up_question : "";
    }

    // 답변 입력창
    const inputArea = findRole(screen, "answer-input");

    if (editable) {
        inputArea.hidden = false;

        const textarea = findRole(screen, "answer-textarea");
        const label = findRole(screen, "answer-label");

        textarea.id = `answer-${question.id}`;
        textarea.dataset.answer = question.id;
        textarea.required = true;
        textarea.value = drafts[question.id] != null ? drafts[question.id] : "";

        label.htmlFor = textarea.id;
    } else {
        // 숨긴 required 입력란 때문에 제출이 막히지 않도록 제거합니다.
        inputArea.remove();
    }

    // 학습 완료 후 모범 답안
    if (phase === "completed") {
        findRole(screen, "model-answer-box").hidden = false;
        setText(screen, "model-answer", question.model_answer);
    }

    return screen;
}


// ----------------------------------------
// 기사와 문제 풀이 화면
// ----------------------------------------

function renderSession() {
    const session = state.session;
    const phase = state.phase;

    const screen = cloneTemplate("tpl-session");

    const headings = {
        answering: "읽고, 생각하고, 답하기",
        followup: "조금 더 깊이 생각해볼까요?",
        evaluation_failed: "답변은 안전하게 저장했어요",
        stopped: "이번 학습을 여기서 마칩니다",
        completed: "모든 문제를 해결했어요!"
    };

    setText(screen, "article-title", session.title);
    setText(screen, "article-text", session.text);
    setText(screen, "heading", headings[phase]);

    // 기사 원문 링크
    const url = safeUrl(session.url);

    if (url) {
        const sourceLink = findRole(screen, "source-link");
        sourceLink.href = url;
        sourceLink.hidden = false;
    }

    // 진행률
    setText(
        screen,
        "progress-label",
        `${session.correct_count} / ${session.questions.length} 해결`
    );

    const progress = findRole(screen, "progress");
    progress.max = session.questions.length;
    progress.value = session.correct_count;

    // 추가 질문 안내
    if (phase === "followup") {
        const guide = findRole(screen, "followup-guide");

        guide.hidden = false;
        guide.textContent =
            `추가 질문 ${state.follow_up_round + 1}차: ` +
            "해결한 문제는 다시 답하지 않아도 됩니다.";
    }

    // 문제 목록
    const questionList = findRole(screen, "question-list");

    session.questions.forEach((question, index) => {
        questionList.append(renderQuestion(question, index));
    });

    // 단계별 버튼과 안내
    if (["answering", "followup"].includes(phase)) {
        const submitButton = findRole(screen, "submit-button");

        submitButton.hidden = false;
        submitButton.textContent = phase === "answering"
            ? "답변 평가받기"
            : "추가 답변 평가받기";
    } else if (phase === "evaluation_failed") {
        findRole(screen, "retry-controls").hidden = false;

    } else if (phase === "stopped") {
        const guide = findRole(screen, "stopped-guide");

        guide.hidden = false;
        guide.textContent =
            `추가 질문 ${state.max_follow_up_rounds}회 한도에 도달했습니다. ` +
            "새 기사를 선택해 학습을 시작할 수 있습니다.";
    }

    if (phase === "completed") {
        // 완료 화면도 먼저 구성한 다음 한 번에 교체합니다.
        const completion = renderCompletion(session);
        view.replaceChildren(screen, completion);

    } else {
            view.replaceChildren(screen);
    }
}


// ----------------------------------------
// 완료 화면: 번역, 추가 지식, 관련 주제
// ----------------------------------------

function renderCompletion(session) {
    const screen = cloneTemplate("tpl-completion");

    setText(screen, "translation", session.translation);

    // 추가 지식
    const knowledgeList = findRole(screen, "knowledge-list");

    for (const knowledge of session.tmi) {
        const item = cloneTemplate("tpl-knowledge-item");

        setText(item, "title", knowledge.title);
        setText(item, "content", knowledge.content);

        knowledgeList.append(item);
    }

    // 관련 주제
    const topicList = findRole(screen, "topic-list");

    session.related_topics.forEach((topic, index) => {
        const card = cloneTemplate("tpl-topic-card");
        const button = card.querySelector("button");

        button.dataset.topic = String(index);

        setText(card, "number", `NEXT CHAPTER ${index + 1}`);
        setText(card, "title", topic.topic);
        setText(card, "summary", topic.summary);
        setText(
          card,
          "connection",
          `이전 기사와의 연결: ${topic.connection}`
        );

        topicList.append(card);
    });

    screen.querySelector("#interest").value = interestDraft;

    return screen;
}





// 컨텐츠 표현할 메인 프레임.
const view = document.querySelector("#view");

// 로딩 표시와 안내.
const notice = document.querySelector("#notice");

// 로딩 표시.
const busy = document.querySelector("#busy");

// 로딩 안내 문구.
const busyText = document.querySelector("#busy-text");

// 새 기사 찾기 버튼.
const restart = document.querySelector("#restart");


// 새 기사 찾기 버튼 클릭.
restart.addEventListener("click", () => {

    if (working) return;

    if (state !== null && state !== undefined) {
        if (
            state.session &&
            confirm("현재 학습을 종료하고 새 기사를 찾을까요?") === false
        ) {
            return;
        }
    }

    act("start", {}, "새로운 기사를 찾고 있습니다...");
});

// 메인 컨텐츠 영역.
view.addEventListener("click", event => {
    const button = event.target.closest("button");
    if (!button || working) return;

    if (button.dataset.action === "start") {
        act("start", {}, "뉴스를 검색하고 학습할 기사를 고르고 있습니다...");

    } else if (button.dataset.action === "retry") {
        act("retry", {}, "저장된 답변을 다시 평가하고 있습니다...");

    } else if (button.dataset.article !== undefined) {
        act("select_article", { index: Number(button.dataset.article) }, "기사와 독해 문제를 준비하고 있습니다...");

    } else if (button.dataset.topic !== undefined) {
        act("next", { topic_index: Number(button.dataset.topic) }, "관련 기사 본문을 검색하고 다음 학습을 준비하고 있습니다...");
    
    }
});

// 문제에 대한 답변하고 제출 시.. or
// 문제를 해결하고 관심 주제 선택 시..
view.addEventListener("submit", event => {
    event.preventDefault();
    if (working) return;

    if (event.target.id === "answers-form") {
        const answers = {};

        event.target.querySelectorAll("[data-answer]").forEach(element => {
            answers[element.dataset.answer] = element.value;
        });

        act("submit", { answers }, "답변을 읽고 이해도를 확인하고 있습니다...");
    } else if (event.target.id === "interest-form") {
        act("next", {interest: event.target.querySelector("#interest").value}, "관심 주제와 연결되는 기사를 찾고 있습니다...");

    }
});


// ----------------------------------------
// 초기 상태 불러오기
// ----------------------------------------

async function initialize() {
    setBusy(true, "학습 공간을 불러오고 있습니다...");

    try {
        const response = await fetch("/api/state");
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "상태를 불러오지 못했습니다.");
        }

        state = data.state;
        render();

    } catch (error) {
        showError(error.message || "서버와 연결하지 못했습니다.");

    } finally {
        setBusy(false);

    }
}

initialize();