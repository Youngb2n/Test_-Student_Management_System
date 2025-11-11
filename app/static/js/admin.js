/* app/static/js/admin.js*/

// 아코디언(사이드바)
function toggleMenu(headerEl) {
  const section = headerEl.closest('.menu-section');
  const submenu = section.querySelector('.submenu');
  const sidebar = section.closest('.side');
  const willOpen = !section.classList.contains('open');
  sidebar.querySelectorAll('.menu-section').forEach(sec => {
    sec.classList.remove('open');
    sec.querySelector('.submenu')?.classList.remove('open');
  });
  if (willOpen) {
    section.classList.add('open');
    submenu?.classList.add('open');
  }
}

// 본문 섹션 토글
function toggleSection(headerEl) {
  headerEl.nextElementSibling.classList.toggle("open");
}

// ===== 입학년도 2000~2100 옵션 생성 =====
function fillAdmissionYears() {
  // 1) 커스텀 드롭다운 구조 (권장: 현재 사용 중)
  const menu = document.getElementById('admission_year_dropdown');
  if (menu) {
    // 이미 옵션이 채워졌으면 스킵
    if (menu.querySelector('.custom-dropdown-option')) return;

    const frag = document.createDocumentFragment();
    for (let y = 2000; y <= 2100; y++) {
      const div = document.createElement('div');
      div.className = 'custom-dropdown-option';
      div.setAttribute('data-value', String(y));
      div.textContent = String(y);
      frag.appendChild(div);
    }
    menu.appendChild(frag);
    return; // 커스텀 경로로 끝
  }

  // 2) 레거시 <select id="admission_year"> 지원
  const sel = document.getElementById('admission_year');
  if (!sel || sel.tagName !== 'SELECT') return;

  if (sel.options && sel.options.length > 1) return;
  for (let y = 2000; y <= 2100; y++) {
    const opt = document.createElement('option');
    opt.value = String(y);
    opt.textContent = String(y);
    sel.appendChild(opt);
  }
}

// ===== 필수 필드 간단 검증(서버 가기 전) =====
document.addEventListener("submit", (e) => {
  const form = e.target;
  if (!form.matches(".form-grid")) return;

  const requiredIds = [
    // 기본정보
    "student_no","name_kor","name_eng","birthdate","phone","email_other","nationality","degree",
    // 재학정보
    "college","department","major","admission_year","admission_term","admission_type",
    "workplace","academic_status","advisor_name","prev_degree","prev_major","researcher_id",
  ];
  const missing = [];
  requiredIds.forEach(id => {
    const el = form.querySelector("#" + id);
    if (el && !String(el.value || "").trim()) missing.push(id);
  });

  if (missing.length) {
    e.preventDefault();
    alert("필수 항목을 입력해 주세요: " + missing.join(", "));
    form.querySelector("#" + missing[0])?.focus();
  }
});

document.addEventListener('DOMContentLoaded', () => {
  // 사이드바 활성 섹션 열기
  const activeLink = document.querySelector('.submenu a.active');
  if (activeLink) {
    const section = activeLink.closest('.menu-section');
    const sidebar = section.closest('.side');
    sidebar.querySelectorAll('.menu-section').forEach(sec => {
      sec.classList.remove('open');
      sec.querySelector('.submenu')?.classList.remove('open');
    });
    section.classList.add('open');
    section.querySelector('.submenu')?.classList.add('open');
  }
  fillAdmissionYears();
});
