/**
 * card-layout-editor.js — Now Page card layout drag-and-drop editor.
 *
 * Manages two Sortable.js zones:
 *   #active-grid  — cards currently in the layout (ordered)
 *   #card-palette — available cards not yet in the layout
 *
 * On any change the active grid is serialised to JSON and written into the
 * hidden <textarea name="layout_json"> so the form POST carries the full
 * layout when the operator clicks Save.
 *
 * Keyboard alternatives are provided for every drag action so the editor
 * is fully operable without a pointing device (WCAG 2.1 AA §2.1.1).
 *
 * Duplicate prevention: a card type can appear at most once across both
 * zones combined.  The Sortable group config enforces this via the
 * onAdd callback.
 */
(function () {
  "use strict";

  /** Serialise the active grid to the hidden textarea. */
  function serializeLayout() {
    var items = document.querySelectorAll("#active-grid .card-editor-item");
    var cards = [];
    items.forEach(function (el) {
      var sel = el.querySelector(".footprint-select");
      var footprint, rowSpan;
      if (sel) {
        var parts = sel.value.split(":");
        footprint = parts[0];
        rowSpan = parseFloat(parts[1]) || 1;
      } else {
        footprint = el.dataset.footprint || "tile";
        rowSpan = parseFloat(el.dataset.rowspan) || 1;
      }
      cards.push({
        type: el.dataset.type,
        footprint: footprint,
        rowSpan: rowSpan,
      });
    });
    var ta = document.getElementById("layout-json");
    if (ta) {
      ta.value = JSON.stringify({ version: 1, cards: cards });
    }
  }

  /** Update the empty-state message visibility in the active grid. */
  function updateEmptyState() {
    var grid = document.getElementById("active-grid");
    if (!grid) return;
    var items = grid.querySelectorAll(".card-editor-item");
    var emptyMsg = grid.querySelector(".empty-grid-msg");
    if (items.length === 0) {
      if (!emptyMsg) {
        var p = document.createElement("p");
        p.className = "empty-grid-msg";
        p.setAttribute("role", "status");
        p.setAttribute("aria-live", "polite");
        p.setAttribute("aria-atomic", "true");
        p.textContent = "No cards in the layout. Add cards from the palette below.";
        grid.appendChild(p);
      }
    } else if (emptyMsg) {
      emptyMsg.remove();
    }
  }

  /**
   * Move a card item from the palette to the active grid.
   * Duplicate prevention: if the type is already present in the active grid
   * the item is silently left in place.
   */
  function addToGrid(item) {
    var grid = document.getElementById("active-grid");
    if (!grid) return;
    var existingType = item.dataset.type;
    var alreadyActive = grid.querySelector(
      '[data-type="' + CSS.escape(existingType) + '"]'
    );
    if (alreadyActive) {
      return;
    }
    grid.appendChild(item);
    serializeLayout();
    updateEmptyState();
  }

  /** Move a card item from the active grid back to the palette. */
  function removeFromGrid(item) {
    var palette = document.getElementById("card-palette");
    if (palette) {
      palette.appendChild(item);
    }
    serializeLayout();
    updateEmptyState();
  }

  // ---------------------------------------------------------------------------
  // Sortable.js initialisation
  // ---------------------------------------------------------------------------

  var activeGrid = document.getElementById("active-grid");
  var cardPalette = document.getElementById("card-palette");

  if (typeof Sortable !== "undefined") {
    if (activeGrid) {
      Sortable.create(activeGrid, {
        group: {
          name: "cards",
          pull: true,
          put: function (to, from, dragEl) {
            // Only allow a type into the grid if it isn't already there.
            var existingType = dragEl.dataset.type;
            return !activeGrid.querySelector(
              '[data-type="' + CSS.escape(existingType) + '"]'
            );
          },
        },
        animation: 150,
        handle: ".drag-handle",
        ghostClass: "sortable-ghost",
        onEnd: serializeLayout,
        onAdd: serializeLayout,
        onRemove: serializeLayout,
      });
    }

    if (cardPalette) {
      Sortable.create(cardPalette, {
        group: {
          name: "cards",
          pull: true,
          put: true,
        },
        animation: 150,
        ghostClass: "sortable-ghost",
        // Palette items don't show a drag handle — the whole item is draggable.
        onEnd: serializeLayout,
        onAdd: serializeLayout,
        onRemove: serializeLayout,
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Keyboard / button event delegation
  // ---------------------------------------------------------------------------

  document.addEventListener("click", function (e) {
    var btn = e.target.closest("button");
    if (!btn) return;
    var item = btn.closest(".card-editor-item");
    if (!item) return;

    if (btn.classList.contains("btn-move-up")) {
      var prev = item.previousElementSibling;
      if (prev) {
        item.parentNode.insertBefore(item, prev);
        serializeLayout();
      }
      // Keep focus on the button so keyboard users don't lose their position.
      btn.focus();
      return;
    }

    if (btn.classList.contains("btn-move-down")) {
      var next = item.nextElementSibling;
      if (next) {
        item.parentNode.insertBefore(next, item);
        serializeLayout();
      }
      btn.focus();
      return;
    }

    if (btn.classList.contains("btn-remove")) {
      removeFromGrid(item);
      // Focus the first palette item's Add button so keyboard flow continues.
      var firstAddBtn = document.querySelector(
        "#card-palette .card-editor-item .btn-add"
      );
      if (firstAddBtn) firstAddBtn.focus();
      return;
    }

    if (btn.classList.contains("btn-add")) {
      addToGrid(item);
      // Focus the last active-grid item's Remove button so keyboard flow
      // continues naturally in the grid.
      var lastRemoveBtn = (function () {
        var removes = document.querySelectorAll(
          "#active-grid .card-editor-item .btn-remove"
        );
        return removes.length ? removes[removes.length - 1] : null;
      })();
      if (lastRemoveBtn) lastRemoveBtn.focus();
      return;
    }
  });

  // ---------------------------------------------------------------------------
  // Footprint selector change handler
  // ---------------------------------------------------------------------------

  document.addEventListener("change", function (e) {
    if (!e.target.classList.contains("footprint-select")) return;
    var parts = e.target.value.split(":");
    var item = e.target.closest(".card-editor-item");
    if (item) {
      item.dataset.footprint = parts[0];
      item.dataset.rowspan = parts[1] || "1";
    }
    serializeLayout();
  });

  // ---------------------------------------------------------------------------
  // Initial serialise so the textarea is populated before any interaction.
  // ---------------------------------------------------------------------------

  serializeLayout();
})();
