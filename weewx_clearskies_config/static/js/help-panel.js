/**
 * help-panel.js — Toggle, keyboard, and HTMX integration for the
 * contextual help side panel.
 *
 * Vanilla JS, no framework dependencies. Works with HTMX-swapped content
 * via event delegation.
 *
 * Expected DOM:
 *   #help-panel           — the <aside> panel element
 *   #help-panel-content   — scrollable content container inside the panel
 *   .help-panel-close     — close button(s) inside the panel
 *   .help-panel-backdrop  — semi-transparent overlay (mobile)
 *   .help-trigger          — ? button(s); each carries data-help-url
 */

(function () {
  "use strict";

  /** Track which help URLs have already been loaded so we only fetch once. */
  var loadedUrls = {};

  /** Element that had focus before the panel opened (for focus return). */
  var previousFocus = null;

  /**
   * Open the help panel.  On first open for a given URL, trigger an HTMX
   * fetch to load the help content fragment.
   *
   * @param {string} helpUrl - The URL to load help content from.
   * @param {HTMLElement} triggerEl - The button that opened the panel.
   */
  function openPanel(helpUrl, triggerEl) {
    var panel = document.getElementById("help-panel");
    var content = document.getElementById("help-panel-content");
    var backdrop = document.querySelector(".help-panel-backdrop");
    if (!panel || !content) return;

    previousFocus = triggerEl || document.activeElement;

    // Load content on first open for this URL.
    if (helpUrl && !loadedUrls[helpUrl]) {
      loadedUrls[helpUrl] = true;
      content.innerHTML = '<p style="color:var(--pico-muted-color)">Loading...</p>';
      if (typeof htmx !== "undefined") {
        htmx.ajax("GET", helpUrl, { target: "#help-panel-content", swap: "innerHTML" });
      }
    }

    panel.classList.add("help-panel--open");
    if (backdrop) backdrop.classList.add("help-panel-backdrop--visible");

    // Update aria-expanded on the trigger.
    if (triggerEl) triggerEl.setAttribute("aria-expanded", "true");

    // Move focus to the panel heading or close button.
    setTimeout(function () {
      var heading = panel.querySelector("h3");
      if (heading) {
        heading.setAttribute("tabindex", "-1");
        heading.focus({ preventScroll: true });
      } else {
        var closeBtn = panel.querySelector(".help-panel-close");
        if (closeBtn) closeBtn.focus({ preventScroll: true });
      }
    }, 50);

    // Persist state.
    try { sessionStorage.setItem("help-panel-open", "1"); } catch (e) { /* ignore */ }
  }

  /**
   * Close the help panel and return focus to the trigger element.
   */
  function closePanel() {
    var panel = document.getElementById("help-panel");
    var backdrop = document.querySelector(".help-panel-backdrop");
    if (!panel) return;

    panel.classList.remove("help-panel--open");
    if (backdrop) backdrop.classList.remove("help-panel-backdrop--visible");

    // Reset aria-expanded on all triggers.
    var triggers = document.querySelectorAll(".help-trigger[aria-expanded='true']");
    for (var i = 0; i < triggers.length; i++) {
      triggers[i].setAttribute("aria-expanded", "false");
    }

    // Return focus.
    if (previousFocus && typeof previousFocus.focus === "function") {
      previousFocus.focus({ preventScroll: true });
      previousFocus = null;
    }

    try { sessionStorage.setItem("help-panel-open", "0"); } catch (e) { /* ignore */ }
  }

  /**
   * Initialize help panel event listeners. Called on DOMContentLoaded.
   * Uses event delegation so dynamically added triggers (HTMX swaps) work.
   */
  function initHelpPanel() {
    // Delegate clicks on .help-trigger buttons (works with HTMX-swapped content).
    document.addEventListener("click", function (e) {
      var trigger = e.target.closest(".help-trigger");
      if (trigger) {
        e.preventDefault();
        var panel = document.getElementById("help-panel");
        var isOpen = panel && panel.classList.contains("help-panel--open");
        if (isOpen) {
          closePanel();
        } else {
          var helpUrl = trigger.getAttribute("data-help-url") || "";
          openPanel(helpUrl, trigger);
        }
        return;
      }

      // Close button.
      if (e.target.closest(".help-panel-close")) {
        e.preventDefault();
        closePanel();
        return;
      }

      // Backdrop click (mobile).
      if (e.target.closest(".help-panel-backdrop")) {
        closePanel();
      }
    });

    // Close on Escape key.
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        var panel = document.getElementById("help-panel");
        if (panel && panel.classList.contains("help-panel--open")) {
          closePanel();
        }
      }
    });
  }

  // Initialize when the DOM is ready.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initHelpPanel);
  } else {
    initHelpPanel();
  }
})();
