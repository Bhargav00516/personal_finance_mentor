/* Personal Finance Mentor — client scripts */


/* ——— Toast Notifications ——— */

function toast(message, type = "success") {
  const el = document.createElement("div");
  el.className = `toast-notify ${type}`;
  el.textContent = message;
  document.body.appendChild(el);

  setTimeout(() => el.remove(), 3200);
}


/* ——— Currency Formatting ——— */

function formatINR(n) {
  return Number(n || 0).toLocaleString("en-IN", {
    maximumFractionDigits: 0,
  });
}


/* ——— Chat ——— */

let chatModalInstance = null;

function openChat() {
  const el = document.getElementById("chatModal");
  if (!el) return;

  if (!chatModalInstance) {
    chatModalInstance = bootstrap.Modal.getOrCreateInstance(el);
  }

  chatModalInstance.show();
}

async function sendChat() {
  const input = document.getElementById("chatInput");
  if (!input) return;

  const msg = input.value.trim();
  if (!msg) return;

  appendChat("user", msg);
  input.value = "";

  const box = document.getElementById("chatMessages");
  if (!box) return;

  const typing = document.createElement("div");
  typing.className = "message ai";
  typing.id = "chatTyping";
  typing.innerHTML =
    '<div class="message-bubble text-muted">Thinking…</div>';

  box.appendChild(typing);
  box.scrollTop = box.scrollHeight;

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message: msg,
      }),
    });

    const data = await res.json();

    document.getElementById("chatTyping")?.remove();

    appendChat(
      "ai",
      data.response || "I could not complete that answer."
    );
  } catch (error) {
    document.getElementById("chatTyping")?.remove();

    appendChat(
      "ai",
      "Something went wrong. Please try again."
    );
  }
}

function appendChat(role, text) {
  const box = document.getElementById("chatMessages");
  if (!box) return;

  const div = document.createElement("div");
  div.className = `message ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  bubble.style.whiteSpace = "pre-line";
  bubble.textContent = String(text || "");

  div.appendChild(bubble);
  box.appendChild(div);

  box.scrollTop = box.scrollHeight;
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("chatInput")?.addEventListener(
    "keypress",
    (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendChat();
      }
    }
  );
});


/* ——— Reset Data ——— */

async function resetData() {
  if (
    !confirm(
      "This permanently deletes all your financial data. Continue?"
    )
  ) {
    return;
  }

  try {
    const res = await fetch("/reset-data", {
      method: "POST",
    });

    const data = await res.json();

    if (data.success) {
      toast("Data reset successfully");

      setTimeout(() => {
        window.location.href = "/";
      }, 1000);
    } else {
      toast(data.error || "Reset failed", "error");
    }
  } catch (error) {
    toast("Reset failed", "error");
  }
}


/* ——— Calculators ——— */

async function runCalc(payload, resultId) {
  const target = document.getElementById(resultId);
  if (!target) return;

  target.innerHTML = `
    <div class="text-muted small">
      Calculating…
    </div>
  `;

  try {
    const res = await fetch("/api/calculate", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    const result = await res.json();

    if (!res.ok || result.error) {
      target.textContent = result.error || "Calculation failed.";
      target.className = "text-danger small";
      return;
    }

    if (payload.type === "investment") {
      target.innerHTML = `
        <div class="d-flex justify-content-between py-1">
          <span class="text-muted">Invested</span>
          <strong>₹${formatINR(result.total_invested)}</strong>
        </div>

        <div class="d-flex justify-content-between py-1">
          <span class="text-muted">Future value</span>
          <strong>₹${formatINR(result.future_value)}</strong>
        </div>

        <div class="d-flex justify-content-between py-1">
          <span class="text-muted">Net gain</span>
          <strong class="${
            result.net_profit >= 0
              ? "text-accent"
              : "text-danger"
          }">
            ₹${formatINR(result.net_profit)}
          </strong>
        </div>
      `;
    } else if (payload.type === "emi") {
      target.innerHTML = `
        <div class="d-flex justify-content-between py-1">
          <span class="text-muted">Monthly EMI</span>
          <strong>₹${formatINR(result.emi)}</strong>
        </div>

        <div class="d-flex justify-content-between py-1">
          <span class="text-muted">Total payment</span>
          <strong>₹${formatINR(result.total_payment)}</strong>
        </div>

        <div class="d-flex justify-content-between py-1">
          <span class="text-muted">Total interest</span>
          <strong>₹${formatINR(result.total_interest)}</strong>
        </div>
      `;
    } else if (payload.type === "goal") {
      const row1 = document.createElement("div");
      row1.className = "d-flex justify-content-between py-1";

      const label1 = document.createElement("span");
      label1.className = "text-muted";
      label1.textContent = "Monthly savings needed";

      const value1 = document.createElement("strong");
      value1.textContent = `₹${formatINR(result.monthly_savings)}`;

      row1.appendChild(label1);
      row1.appendChild(value1);

      const row2 = document.createElement("div");
      row2.className = "d-flex justify-content-between py-1";

      const label2 = document.createElement("span");
      label2.className = "text-muted";
      label2.textContent = "Total contributions";

      const value2 = document.createElement("strong");
      value2.textContent = `₹${formatINR(result.total_savings)}`;

      row2.appendChild(label2);
      row2.appendChild(value2);

      const note = document.createElement("p");
      note.className = "small text-muted mt-2 mb-0";
      note.textContent =
        result.note ||
        "Compare with your actual surplus before committing.";

      target.innerHTML = "";
      target.appendChild(row1);
      target.appendChild(row2);
      target.appendChild(note);
    }
  } catch (error) {
    console.error("Calculation error:", error);

    target.innerHTML = `
      <div class="text-danger small">
        Calculation failed
      </div>
    `;
  }
}


/* ——— Calculator Modal ——— */

function openCalcModal(type) {
  const modalElement = document.getElementById("calcModal");
  const title = document.getElementById("calcTitle");
  const body = document.getElementById("calcBody");

  if (!modalElement || !title || !body) return;

  const modal = bootstrap.Modal.getOrCreateInstance(modalElement);

  if (type === "investment") {
    title.textContent = "Investment calculator";

    body.innerHTML = `
      <div class="mb-3">
        <label class="form-label">Initial amount (₹)</label>
        <input type="number" id="cP" class="form-control"
          value="10000" min="0">
      </div>

      <div class="mb-3">
        <label class="form-label">Expected annual return (%)</label>
        <input type="number" id="cR" class="form-control"
          value="12" step="0.1">
      </div>

      <div class="mb-3">
        <label class="form-label">Years</label>
        <input type="number" id="cY" class="form-control"
          value="5" min="1">
      </div>

      <div class="mb-3">
        <label class="form-label">Monthly contribution (₹)</label>
        <input type="number" id="cM" class="form-control"
          value="0" min="0">
      </div>

      <button id="investmentCalculateBtn"
        class="btn btn-primary w-100" type="button">
        Calculate
      </button>

      <div id="calcResult" class="mt-3"></div>
    `;

    document
      .getElementById("investmentCalculateBtn")
      ?.addEventListener("click", () => {
        runCalc(
          {
            type: "investment",
            principal: Number(document.getElementById("cP").value),
            profit_rate: Number(document.getElementById("cR").value),
            time_years: Number(document.getElementById("cY").value),
            monthly_contribution: Number(
              document.getElementById("cM").value
            ),
          },
          "calcResult"
        );
      });
  }

  else if (type === "emi") {
    title.textContent = "EMI calculator";

    body.innerHTML = `
      <div class="mb-3">
        <label class="form-label">Loan amount (₹)</label>
        <input type="number" id="cL" class="form-control"
          value="500000" min="0">
      </div>

      <div class="mb-3">
        <label class="form-label">Interest rate (% p.a.)</label>
        <input type="number" id="cIR" class="form-control"
          value="10.5" step="0.1" min="0">
      </div>

      <div class="mb-3">
        <label class="form-label">Tenure (years)</label>
        <input type="number" id="cT" class="form-control"
          value="5" min="1">
      </div>

      <button id="emiCalculateBtn"
        class="btn btn-primary w-100" type="button">
        Calculate
      </button>

      <div id="calcResult" class="mt-3"></div>
    `;

    document
      .getElementById("emiCalculateBtn")
      ?.addEventListener("click", () => {
        runCalc(
          {
            type: "emi",
            loan_amount: Number(document.getElementById("cL").value),
            interest_rate: Number(
              document.getElementById("cIR").value
            ),
            tenure_months:
              Number(document.getElementById("cT").value) * 12,
          },
          "calcResult"
        );
      });
  }

  else if (type === "goal") {
    title.textContent = "Goal planner";

    body.innerHTML = `
      <div class="mb-3">
        <label class="form-label">Goal amount (₹)</label>
        <input type="number" id="cG" class="form-control"
          value="500000" min="0">
      </div>

      <div class="mb-3">
        <label class="form-label">Years</label>
        <input type="number" id="cGY" class="form-control"
          value="5" min="1">
      </div>

      <div class="mb-3">
        <label class="form-label">Current savings (₹)</label>
        <input type="number" id="cGS" class="form-control"
          value="0" min="0">
      </div>

      <div class="mb-3">
        <label class="form-label">Expected annual return (%)</label>
        <input type="number" id="cGR" class="form-control"
          value="12" step="0.1">
      </div>

      <button id="goalCalculateBtn"
        class="btn btn-primary w-100" type="button">
        Calculate
      </button>

      <div id="calcResult" class="mt-3"></div>
    `;

    document
      .getElementById("goalCalculateBtn")
      ?.addEventListener("click", () => {
        runCalc(
          {
            type: "goal",
            goal_amount: Number(document.getElementById("cG").value),
            time_years: Number(document.getElementById("cGY").value),
            current_savings: Number(
              document.getElementById("cGS").value
            ),
            expected_return: Number(
              document.getElementById("cGR").value
            ),
          },
          "calcResult"
        );
      });
  }

  modal.show();
}


/* ——— Credit Education ——— */

function cleanCreditText(text) {
  return String(text || "")
    .replace(/\*\*/g, "")
    .replace(/__/g, "")
    .replace(/\*/g, "")
    .replace(/^\s*\d+\\?\.\s*/, "")
    .replace(/^\s*[-•]\s*/, "")
    .trim();
}

function createCreditPointList(points) {
  const list = document.createElement("ol");
  list.className = "ps-3 mb-0";

  points.slice(0, 5).forEach((point) => {
    const item = document.createElement("li");
    item.className = "mb-3";
    item.textContent = cleanCreditText(point);
    list.appendChild(item);
  });

  return list;
}

async function openCreditTips() {
  const modalElement = document.getElementById("creditModal");
  const body = document.getElementById("creditBody");

  if (!modalElement || !body) {
    console.error("Credit modal elements not found.");
    return;
  }

  const modal = bootstrap.Modal.getOrCreateInstance(modalElement);

  body.innerHTML = `
    <div class="text-center py-4 text-muted">
      Loading credit education...
    </div>
  `;

  modal.show();

  try {
    const res = await fetch("/api/credit-tips", {
      method: "GET",
      headers: {
        Accept: "application/json",
      },
    });

    if (!res.ok) {
      throw new Error(`HTTP error: ${res.status}`);
    }

    const data = await res.json();

    if (data.error) {
      throw new Error(data.error);
    }

    const score =
      data.credit_score !== null &&
      data.credit_score !== undefined &&
      data.credit_score !== ""
        ? data.credit_score
        : "Not available";

    const category = cleanCreditText(
      data.category || "Not classified"
    );

    const points = Array.isArray(data.points)
      ? data.points
          .slice(0, 5)
          .map(cleanCreditText)
          .filter(Boolean)
      : [];

    body.innerHTML = "";

    const scoreSection = document.createElement("div");
    scoreSection.className = "mb-4";

    const scoreTitle = document.createElement("h5");
    scoreTitle.className = "mb-2";
    scoreTitle.textContent = "Your Credit Score";

    const scoreValue = document.createElement("div");
    scoreValue.className = "display-6 fw-bold text-accent";
    scoreValue.textContent = String(score);

    const scoreCategory = document.createElement("p");
    scoreCategory.className = "text-muted mb-0";
    scoreCategory.textContent = `Category: ${category}`;

    scoreSection.appendChild(scoreTitle);
    scoreSection.appendChild(scoreValue);
    scoreSection.appendChild(scoreCategory);

    body.appendChild(scoreSection);

    const pointsTitle = document.createElement("h6");
    pointsTitle.className = "mb-3";
    pointsTitle.textContent = "Personalized Credit Guidance";

    body.appendChild(pointsTitle);

    if (points.length > 0) {
      body.appendChild(createCreditPointList(points));
    }

    const tips =
      typeof data.tips === "string" ? data.tips.trim() : "";

    if (tips) {
      const explanationTitle = document.createElement("h6");
      explanationTitle.className = "mt-4 mb-2";
      explanationTitle.textContent = "Additional Explanation";

      body.appendChild(explanationTitle);

      const explanation = document.createElement("div");
      explanation.className = "credit-guidance";
      explanation.style.whiteSpace = "pre-wrap";
      explanation.textContent = cleanCreditText(tips);

      body.appendChild(explanation);
    }

    if (!tips && points.length === 0) {
      const emptyMessage = document.createElement("p");
      emptyMessage.className = "text-muted";
      emptyMessage.textContent =
        "Credit guidance is currently unavailable.";

      body.appendChild(emptyMessage);
    }
  } catch (error) {
    console.error("Credit education error:", error);

    body.innerHTML = `
      <div class="text-center py-4">
        <p class="text-muted mb-2">
          Could not load credit education.
        </p>

        <button
          class="btn btn-outline-secondary btn-sm"
          onclick="openCreditTips()">
          Try Again
        </button>
      </div>
    `;
  }
}


/* ——— Download Report ——— */

function downloadReport() {
  const report = document.querySelector(".report-body");
  if (!report) return;

  const html = `
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>Financial report</title>

      <style>
        body {
          font-family: system-ui;
          padding: 2rem;
          max-width: 720px;
          margin: auto;
          line-height: 1.6;
          color: #111;
        }
      </style>
    </head>

    <body>
      <h1>Financial education report</h1>
      ${report.innerHTML}
    </body>
    </html>
  `;

  const a = document.createElement("a");

  const url = URL.createObjectURL(
    new Blob([html], {
      type: "text/html",
    })
  );

  a.href = url;
  a.download = "financial_report.html";
  a.click();

  setTimeout(() => URL.revokeObjectURL(url), 1000);
}