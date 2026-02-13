# UI Guidelines

This project uses a lightweight shared design system in:
- `dogadoption_admin/static/css/ui_system.css`
- `dogadoption_admin/static/js/ui_system.js`

## 1. Core Principles
- Prioritize clarity over decoration.
- Keep forms single-column by default.
- Use explicit labels, helper text, and visible validation states.
- Do not change backend business rules in UI-only work.
- Design mobile-first, then enhance for larger screens.

## 2. Design Tokens
- Typography:
  - Display: `Sora`
  - Body: `Nunito Sans`
- Spacing: `--space-1` to `--space-7`
- Radius: `--radius-sm` to `--radius-xl`
- Elevation: `--shadow-1`, `--shadow-2`
- Colors:
  - Primary: `--color-primary`
  - Success: `--color-success`
  - Warning: `--color-warning`
  - Danger: `--color-danger`
  - Surface/Text/Border tokens for both light and dark schemes

Always use token variables instead of hardcoded colors/sizes when possible.

## 3. Component Classes
- Layout:
  - `ui-page`, `ui-page--narrow`, `ui-stack`
- Surfaces:
  - `ui-card`, `ui-card__header`, `ui-card__body`, `ui-card__title`, `ui-card__subtitle`
- Buttons:
  - `ui-btn`, `ui-btn--primary`, `ui-btn--secondary`, `ui-btn--success`, `ui-btn--danger`, `ui-btn--warning`, `ui-btn--full`
- Forms:
  - `ui-form`, `ui-field`, `ui-label`, `ui-hint`, `ui-input`, `ui-select`, `ui-textarea`
  - Validation: `form-error-summary`, `is-invalid`, `ui-field-error`
- Feedback:
  - `ui-alert`, `ui-alert--success`, `ui-alert--warning`, `ui-alert--danger`, `ui-alert--info`
  - `ui-toast-stack` for message lists
- Other primitives:
  - `ui-check`, `ui-radio`, `ui-toggle`
  - `ui-table`, `ui-badge`, `ui-tabs`, `ui-tab`
  - `ui-modal`, `ui-modal__dialog`
  - `ui-tooltip`

## 4. Form UX Rules
- Every input must have an associated `<label for=\"...\">`.
- Avoid placeholder-only forms; placeholders are optional hints.
- Use `form.js-validate` + `novalidate` to enable shared validation behavior.
- Include one top summary container:
  - `<div class=\"form-error-summary\" hidden role=\"alert\" aria-live=\"assertive\"></div>`
- Add `data-disable-submit=\"true\"` on forms that should prevent double-submit.
- Add `data-loading-text=\"...\"` on submit buttons for loading feedback.
- Group optional or advanced fields using `details` or separate sections.

## 5. Accessibility Requirements
- Keyboard reachable interactive elements only.
- Preserve visible focus ring (`:focus-visible`) from the design system.
- Use `aria-live` for dynamic status/error messaging.
- Do not rely on color alone to communicate errors/status.
- Maintain sufficient contrast for text and controls.

## 6. Responsive Behavior
- Default to single-column forms.
- Use `ui-form__grid ui-form__grid--2` only when fields are short and tightly related.
- Keep touch targets large enough (minimum ~44px interaction height where practical).
- Test at mobile widths before desktop polish.

## 7. Implementation Checklist
- Tokens used instead of ad-hoc values
- Form labels + helper text present
- Error summary and inline invalid states wired
- Double-submit protection where needed
- Success/warning/error feedback visible
- Keyboard and focus behavior verified
- Mobile layout verified
