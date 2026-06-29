/**
 * conditional-visibility.js — Shared conditional field show/hide handler.
 *
 * Reads data-condition-field, data-condition-op, and data-condition-value
 * attributes from wrapper elements produced by the render_field Jinja2 macro.
 *
 * Supported operators (data-condition-op):
 *   eq  — controlling field value equals data-condition-value
 *   ne  — controlling field value does not equal data-condition-value
 *   in  — data-condition-value is a JSON array; field value must be one of them
 *
 * Multiple conditions (OR logic): when data-condition-field is a JSON array,
 * the element is shown if ANY single condition evaluates to true.
 *
 * When a condition is false:  aria-hidden="true" + inert attribute are set.
 * When a condition is true:   aria-hidden and inert are removed.
 * Using inert ensures hidden fields are excluded from form submission and
 * keyboard navigation (WCAG 2.1 AA §2.1.1).
 *
 * No framework or library dependency — DOM API only.
 */
(function () {
  "use strict";

  /** Return the current value of a named form control (radio, select, input). */
  function getFieldValue(name) {
    var radio = document.querySelector('input[type="radio"][name="' + name + '"]:checked');
    if (radio) return radio.value;
    var select = document.querySelector('select[name="' + name + '"]');
    if (select) return select.value;
    var input = document.querySelector('input[name="' + name + '"]');
    if (input) return input.value;
    return null;
  }

  /** Evaluate a single condition object {field_id, op, value} against the DOM. */
  function evaluateSingle(fieldId, op, condValue) {
    var actual = getFieldValue(fieldId);
    if (actual === null) return false;
    if (op === "eq") return actual === condValue;
    if (op === "ne") return actual !== condValue;
    if (op === "in") {
      var allowed = Array.isArray(condValue) ? condValue : JSON.parse(condValue);
      return allowed.indexOf(actual) !== -1;
    }
    return false;
  }

  /** Apply visibility to an element based on its condition attributes. */
  function applyVisibility(el) {
    var rawField = el.dataset.conditionField;
    var rawOp    = el.dataset.conditionOp;
    var rawValue = el.dataset.conditionValue;

    var visible;

    // Detect JSON array (multiple conditions — OR logic).
    if (rawField.charAt(0) === "[") {
      var fields = JSON.parse(rawField);
      var ops    = JSON.parse(rawOp);
      var values = JSON.parse(rawValue);
      visible = false;
      for (var i = 0; i < fields.length; i++) {
        if (evaluateSingle(fields[i], ops[i], values[i])) {
          visible = true;
          break;
        }
      }
    } else {
      // Single condition.
      visible = evaluateSingle(rawField, rawOp, rawValue);
    }

    if (visible) {
      el.removeAttribute("aria-hidden");
      el.removeAttribute("inert");
    } else {
      el.setAttribute("aria-hidden", "true");
      el.setAttribute("inert", "");
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    var conditionalEls = document.querySelectorAll("[data-condition-field]");

    conditionalEls.forEach(function (el) {
      // Resolve the set of controlling field names for this element.
      var rawField = el.dataset.conditionField;
      var names = rawField.charAt(0) === "[" ? JSON.parse(rawField) : [rawField];

      // Register change listeners on every controlling field.
      names.forEach(function (name) {
        var controls = document.querySelectorAll(
          '[name="' + name + '"]'
        );
        controls.forEach(function (ctrl) {
          ctrl.addEventListener("change", function () {
            applyVisibility(el);
          });
        });
      });

      // Evaluate once on load to handle pre-populated forms.
      applyVisibility(el);
    });
  });
}());
