/* app/static/js/login.js*/

document.addEventListener("DOMContentLoaded", () => {
  const studentRadio = document.getElementById("tab-student");
  const adminRadio = document.getElementById("tab-admin");
  const labels = {
    student: document.querySelector('label[for="tab-student"]'),
    admin: document.querySelector('label[for="tab-admin"]'),
  };

  function updateAria() {
    labels.student?.setAttribute("aria-selected", studentRadio.checked ? "true" : "false");
    labels.admin?.setAttribute("aria-selected", adminRadio.checked ? "true" : "false");
  }

  function focusFirstInput() {
    const form =
      document.querySelector("#tab-student:checked ~ .form--student") ||
      document.querySelector("#tab-admin:checked ~ .form--admin");
    const first = form ? form.querySelector("input[type='text'], input[type='password']") : null;
    if (first) first.focus();
  }

  studentRadio?.addEventListener("change", () => { updateAria(); focusFirstInput(); });
  adminRadio?.addEventListener("change", () => { updateAria(); focusFirstInput(); });

  // 초기 상태 반영
  updateAria();
  setTimeout(focusFirstInput, 0);
});
