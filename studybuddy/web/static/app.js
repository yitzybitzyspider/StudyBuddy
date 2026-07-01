/* Inleto/StudyBuddy player (Loop 31): one question per screen, per-question timer,
   review-before-submit. Plain JS, no dependencies. The whole test is ONE form —
   the player only controls visibility, so no-JS still degrades to all-questions-at-once. */

(function () {
  var form = document.querySelector("[data-player]");
  if (!form) return;

  var cards = Array.prototype.slice.call(form.querySelectorAll(".q"));
  if (!cards.length) return;

  var idx = 0;
  var started = Date.now();
  var bar = document.querySelector("[data-progress]");
  var counter = document.querySelector("[data-counter]");
  var prevBtn = form.querySelector("[data-prev]");
  var nextBtn = form.querySelector("[data-next]");
  var reviewPanel = form.querySelector("[data-review]");
  var submitRow = form.querySelector("[data-submit-row]");

  function timeField(card) {
    return card.querySelector("input[data-time]");
  }

  function stamp(card) {
    // accumulate seconds spent on the visible card into its hidden time field
    var f = timeField(card);
    if (!f) return;
    var spent = (Date.now() - started) / 1000;
    f.value = (parseFloat(f.value || "0") + spent).toFixed(1);
    started = Date.now();
  }

  function answered(card) {
    var checked = card.querySelector("input[type=radio]:checked");
    var text = card.querySelector("textarea");
    return !!(checked || (text && text.value.trim()));
  }

  function renderReview() {
    if (!reviewPanel) return;
    var grid = reviewPanel.querySelector("[data-review-grid]");
    grid.innerHTML = "";
    cards.forEach(function (card, i) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "review-cell " + (answered(card) ? "done" : "blank");
      b.textContent = i + 1;
      b.addEventListener("click", function () { show(i); });
      grid.appendChild(b);
    });
  }

  function show(i) {
    stamp(cards[idx]);
    idx = Math.max(0, Math.min(i, cards.length)); // cards.length == review screen
    cards.forEach(function (card, j) { card.style.display = j === idx ? "" : "none"; });
    var inReview = idx === cards.length;
    if (reviewPanel) reviewPanel.style.display = inReview ? "" : "none";
    if (submitRow) submitRow.style.display = inReview ? "" : "none";
    if (inReview) renderReview();
    if (prevBtn) prevBtn.disabled = idx === 0;
    if (nextBtn) nextBtn.textContent = idx >= cards.length - 1 ? "Review →" : "Next →";
    if (nextBtn) nextBtn.style.display = inReview ? "none" : "";
    if (bar) bar.style.width = (100 * Math.min(idx, cards.length) / cards.length) + "%";
    if (counter) counter.textContent = inReview
      ? "Review your answers"
      : "Question " + (idx + 1) + " of " + cards.length;
    window.scrollTo(0, 0);
  }

  if (prevBtn) prevBtn.addEventListener("click", function () { show(idx - 1); });
  if (nextBtn) nextBtn.addEventListener("click", function () { show(idx + 1); });
  form.addEventListener("submit", function () { if (idx < cards.length) stamp(cards[idx]); });

  show(0);
})();
