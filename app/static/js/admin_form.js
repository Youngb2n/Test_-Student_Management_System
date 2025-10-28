// app/static/js/admin_form.js

function closestMatch(el, selector) {
  while (el && el !== document) {
    if (el.matches && el.matches(selector)) return el;
    el = el.parentNode;
  }
  return null;
}
/* ============================
   커스텀 드롭다운 (공통)
   ============================ */

function closeAllDropdowns() {
  document.querySelectorAll(".custom-dropdown-menu.active").forEach(m => {
    m.classList.remove("active");
  });
}

function openDropdown(menuEl, triggerBtn) {
  closeAllDropdowns();
  if (!menuEl) return;

  menuEl.classList.add("active");

  const labelEl = triggerBtn.querySelector(".custom-dropdown-label");
  const currentText = (labelEl?.textContent || "").trim();

  const opts = menuEl.querySelectorAll(".custom-dropdown-option");
  if (!opts.length) return;

  let matched = null;
  opts.forEach(o => {
    o.classList.remove("highlight");
    if (o.getAttribute("data-value") === currentText) {
      matched = o;
    }
  });
  if (!matched) matched = opts[0];
  if (matched) {
    matched.classList.add("highlight");
    matched.scrollIntoView({ block: "nearest" });
  }
}

function selectOptionAndClose(optEl) {
  const menu = optEl.closest(".custom-dropdown-menu");
  if (!menu) return;
  const wrapper = menu.closest(".custom-dropdown-wrapper");
  if (!wrapper) return;

  const value = optEl.getAttribute("data-value");
  const labelEl = wrapper.querySelector(".custom-dropdown-label");
  const hiddenInput = wrapper.querySelector(".custom-dropdown-hidden");

  // 라벨 업데이트
  labelEl.textContent = value ? value : "미입력";

  // 🔹 name 제어 로직 (핵심 부분)
  if (value === "" || value == null) {
    // 미입력 → 서버로 전송하지 않도록 name 제거
    if (!hiddenInput.dataset.originalName) {
      hiddenInput.dataset.originalName = hiddenInput.getAttribute("name");
    }
    hiddenInput.removeAttribute("name");
    hiddenInput.value = "";
  } else {
    // 값이 있으면 name 복구 + 숫자 변환
    if (!hiddenInput.getAttribute("name") && hiddenInput.dataset.originalName) {
      hiddenInput.setAttribute("name", hiddenInput.dataset.originalName);
    }
    hiddenInput.value = parseInt(value, 10);
  }

  // 선택된 옵션 강조 표시
  menu.querySelectorAll(".custom-dropdown-option.highlight").forEach(o => {
    o.classList.remove("highlight");
  });
  optEl.classList.add("highlight");

  menu.classList.remove("active");
}

export function initCustomDropdowns(scope) {
  const root = scope || document;

  root.querySelectorAll(".custom-dropdown-trigger").forEach(btn => {
    if (btn.dataset.bound === "1") return;
    btn.dataset.bound = "1";

    btn.addEventListener("click", ev => {
      ev.stopPropagation();
      const targetId = btn.getAttribute("data-target");
      if (!targetId) return;
      const menu = document.getElementById(targetId);
      if (!menu) return;

      if (menu.classList.contains("active")) menu.classList.remove("active");
      else openDropdown(menu, btn);
    });
  });

  root.querySelectorAll(".custom-dropdown-menu").forEach(menu => {
    menu.querySelectorAll(".custom-dropdown-option").forEach(opt => {
      if (opt.dataset.bound === "1") return;
      opt.dataset.bound = "1";
      opt.addEventListener("click", () => selectOptionAndClose(opt));
    });
  });

  document.addEventListener("click", () => {
    closeAllDropdowns();
  });
}

// 키보드 네비(드롭다운 open 상태에서 ↑↓Enter...)
document.addEventListener("keydown", e => {
  const menu = document.querySelector(".custom-dropdown-menu.active");
  if (!menu) return;
  const opts = Array.from(menu.querySelectorAll(".custom-dropdown-option"));
  if (!opts.length) return;

  // 선택
  if (e.key === "Enter") {
    const highlighted = menu.querySelector(".custom-dropdown-option.highlight");
    if (highlighted) {
      selectOptionAndClose(highlighted);
      e.preventDefault();
    }
    return;
  }

  // 위/아래 이동
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    let idx = opts.findIndex(o => o.classList.contains("highlight"));
    if (idx === -1) idx = 0;
    if (e.key === "ArrowDown") {
      idx = Math.min(idx + 1, opts.length - 1);
    } else {
      idx = Math.max(idx - 1, 0);
    }
    opts.forEach(o => o.classList.remove("highlight"));
    const newOpt = opts[idx];
    newOpt.classList.add("highlight");
    newOpt.scrollIntoView({ block: "nearest" });
    e.preventDefault();
    return;
  }

  // ESC
  if (e.key === "Escape") {
    closeAllDropdowns();
    return;
  }
});

// ===== show/hide 블록 유틸 (재직자 전형, 휴학이력 등) =====
export function syncConditionalBlocks() {
  const admissionType  = document.getElementById("admission_type")?.value || "";
  const leaveFlag      = document.getElementById("leave_of_absence")?.value || "N";

  // 재직자 전형 블록
  const employedBlock = document.getElementById("employed_block");
  const isEmployed = admissionType.includes("재직");
  if (employedBlock) {
    employedBlock.style.display = isEmployed ? "block" : "none";

    const workplaceInput = employedBlock.querySelector('input[name="workplace"]');
    const certPathInput  = employedBlock.querySelector('input[name="health_insurance_certificate"]');

    if (isEmployed) {
      if (workplaceInput) workplaceInput.disabled = false;
      if (certPathInput)  certPathInput.disabled  = false;
    } else {
      if (workplaceInput) {
        workplaceInput.value = "";
        workplaceInput.disabled = true;
      }
      if (certPathInput) {
        certPathInput.value = "";
        certPathInput.disabled = true;
      }
    }
  }

  // 휴학 이력 블록
  const leaveBlock = document.getElementById("leave_block");
  if (leaveBlock) {
    const isLeave =
      leaveFlag === "Y" ||
      leaveFlag === "휴학" ||
      (typeof leaveFlag === "string" && leaveFlag.toUpperCase() === "LEAVE");

    leaveBlock.style.display = isLeave ? "block" : "none";

    // 단일화된 name 기준 (지금은 name="leave_year", "leave_semester")
    const yearInputs = leaveBlock.querySelectorAll('input[name="leave_year"]');
    const semSelects = leaveBlock.querySelectorAll('select[name="leave_semester"]');

    if (!isLeave) {
      yearInputs.forEach(i => { i.disabled = true; });
      semSelects.forEach(s => { s.disabled = true; });
    } else {
      yearInputs.forEach(i => { i.disabled = false; });
      semSelects.forEach(s => { s.disabled = false; });
    }
  }
}

// ===== 휴학 이력 row 추가/삭제 =====
let leaveRowIdx = 1;
export function addLeaveRow(currentYear) {
  const container = document.getElementById("leave_rows_container");
  if (!container) return;

  const idx = leaveRowIdx++;
  const wrapper = document.createElement("div");
  wrapper.className = "leave-history-row";

  wrapper.innerHTML = `
    <div class="field inline-mini">
      <label>휴학년도</label>
      <div class="custom-dropdown-wrapper miniwidth">
        <button type="button"
                class="custom-dropdown-trigger"
                data-target="leave_year_dropdown_${idx}">
          <span class="custom-dropdown-label">${currentYear}</span>
          <span class="custom-dropdown-arrow">▼</span>
        </button>

        <div class="custom-dropdown-menu" id="leave_year_dropdown_${idx}">
          ${Array.from({length:101}, (_,i)=>2000+i).map(y=>`
            <div class="custom-dropdown-option" data-value="${y}">${y}</div>
          `).join("")}
        </div>

        <input type="hidden"
               name="leave_year"
               value="${currentYear}"
               class="leave_year_hidden" />
      </div>
    </div>

    <div class="field inline-mini">
      <label>휴학학기</label>
      <select name="leave_semester">
        <option value="1학기">1학기</option>
        <option value="2학기">2학기</option>
        <option value="여름계절">여름계절</option>
        <option value="겨울계절">겨울계절</option>
      </select>
    </div>

    <button type="button" class="btn-ghost-danger btn-leave-remove">🗑 삭제</button>
  `;

  container.appendChild(wrapper);
  initCustomDropdowns(wrapper);
}

export function bindLeaveRows(currentYear) {
  const addBtn = document.getElementById("btn_leave_add");
  const rowsContainer = document.getElementById("leave_rows_container");
  if (addBtn) {
    addBtn.addEventListener("click", () => addLeaveRow(currentYear));
  }
  if (rowsContainer) {
    rowsContainer.addEventListener("click", e => {
      if (e.target.classList.contains("btn-leave-remove")) {
        const row = e.target.closest(".leave-history-row");
        if (row && rowsContainer.querySelectorAll(".leave-history-row").length > 1) {
          row.remove();
        }
      }
    });
  }
}

/* ============================
   교육과정 이수조건 행 추가/삭제
   ============================ */
export function initCurriculumRequirements() {
  const container = document.getElementById("requirements_container");
  if (!container) return;

  const addBtn = document.getElementById("btn_requirement_add");
  if (addBtn && !addBtn.dataset.bound) {
    addBtn.dataset.bound = "1";
    addBtn.addEventListener("click", () => {
      const firstCard = container.querySelector(".requirement-card");
      if (!firstCard) return;

      const clone = firstCard.cloneNode(true);
      clone.querySelectorAll("input").forEach(i => (i.value = ""));
      clone.querySelectorAll("select").forEach(s => (s.selectedIndex = 0));
      container.insertBefore(clone, addBtn);
    });
  }

  if (!container.dataset.bound) {
    container.dataset.bound = "1";
    container.addEventListener("click", e => {
      const btn = closestMatch(e.target, ".btn-requirement-remove");
      if (!btn) return;
      const allCards = container.querySelectorAll(".requirement-card");
      if (allCards.length <= 1) return;
      const card = closestMatch(btn, ".requirement-card");
      if (card) card.remove();
    });
  }
}

// ===== 필수 유효성 검사 등 페이지별에서 호출할 수 있는 헬퍼 =====
export function hasSpace(str) {
  return (/\s/).test(str || "");
}
export function isValidDateYYYYMMDD(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!m) return false;

  const year = parseInt(m[1], 10);
  const month = parseInt(m[2], 10);
  const day = parseInt(m[3], 10);

  if (year < 1900 || year > 2100) return false;
  if (month < 1 || month > 12)   return false;
  if (day   < 1 || day   > 31)   return false;
  return true;
}

export function bindRequirementSkipToggle() {
  const checkbox = document.getElementById("skip_requirements_checkbox");
  const container = document.getElementById("requirements_container");
  if (!checkbox || !container) return;

  checkbox.addEventListener("change", () => {
    const disabled = checkbox.checked;

    // UI 숨김 및 disable 처리
    container.style.display = disabled ? "none" : "block";
    container.querySelectorAll("input, select, button").forEach(el => {
      el.disabled = disabled;
    });
  });
}



// 휴학 이력 중복 검사: 제출 시만 사용
export function hasDuplicateLeaveHistory() {
  const rows = document.querySelectorAll("#leave_rows_container .leave-history-row");
  const seen = new Set();

  for (const row of rows) {
    const yearInput = row.querySelector('input[name="leave_year"]');
    const semSelect = row.querySelector('select[name="leave_semester"]');

    if (!yearInput || !semSelect) continue;

    const yearVal = (yearInput.value || "").trim();
    const semVal  = (semSelect.value || "").trim();
    if (!yearVal || !semVal) continue;

    const key = `${yearVal}::${semVal}`;
    if (seen.has(key)) {
        return {
          dup: true,
          year: yearVal,
          sem: semVal,
        };
    }
    seen.add(key);
  }

  return { dup: false };
}


// reset 버튼 눌렀을 때 UI 상태 초기화
export function resetFormStateToDefault(currentYear) {
  // 재직자 전형 블록 닫기
  const employedBlock = document.getElementById("employed_block");
  if (employedBlock) {
    employedBlock.style.display = "none";
  }

  // 휴학 블록 닫기
  const leaveBlock = document.getElementById("leave_block");
  if (leaveBlock) {
    leaveBlock.style.display = "none";
  }

  // 휴학 이력 행 초기화: 1행만 남기고 나머지 삭제 + 값 초기화
  const container = document.getElementById("leave_rows_container");
  if (container) {
    const rows = Array.from(container.querySelectorAll(".leave-history-row"));

    if (rows.length > 0) {
      const firstRow = rows[0];

      // 나머지 행은 제거
      rows.slice(1).forEach(r => r.remove());

      // 첫 행 연도 hidden 값 초기화
      const firstYearHidden = firstRow.querySelector('input[name="leave_year"]');
      if (firstYearHidden) {
        firstYearHidden.value = currentYear || "";
      }

      // 첫 행 드롭다운 라벨도 초기화
      const firstYearLabel = firstRow.querySelector(".custom-dropdown-label");
      if (firstYearLabel && currentYear) {
        firstYearLabel.textContent = currentYear;
      }

      // 첫 행 학기 select 초기화(첫 옵션)
      const firstSem = firstRow.querySelector('select[name="leave_semester"]');
      if (firstSem) {
        firstSem.selectedIndex = 0;
      }
    }
  }

  // 국적 기타입력칸 초기화/숨김
  const natSel   = document.getElementById("nationality_select");
  const natOther = document.getElementById("nationality_other");
  if (natSel && natOther) {
    if (natSel.value === "__OTHER__") {
      // reset 이후에도 브라우저가 "__OTHER__"를 기본으로 잡아놨다면 열어주고 비우기
      natOther.style.display = "inline-block";
      natOther.value = "";
    } else {
      natOther.style.display = "none";
      natOther.value = "";
    }
  }

  // 개인 이메일 도메인 기타입력칸 초기화/숨김
  const domSel   = document.getElementById("email_other_domain_select");
  const domOther = document.getElementById("email_other_domain_other");
  if (domSel && domOther) {
    // reset 이후엔 select 다시 보이게 만들고, 기타 입력칸은 숨긴다
    domSel.style.display = "inline-block";
    domOther.style.display = "none";
    domOther.value = "";
  }
}

const form = document.querySelector("form.admin-form");
if (form) {
  form.addEventListener("submit", () => {
    // ===== 교육과정 매핑 카드들 처리 =====
    const cards = form.querySelectorAll(".curriculum-map-card");
    cards.forEach(card => {
      const finalYearInput     = card.querySelector('input[name="final_year"]');
      const finalSemesterInput = card.querySelector('select[name="final_semester"]');

      // final_year가 빈 문자열이면 → final_year / final_semester 둘 다 안보내기
      if (finalYearInput && finalYearInput.value.trim() === "") {
        finalYearInput.disabled = true;
        if (finalSemesterInput) {
          finalSemesterInput.disabled = true;
        }
      } else {
        // final_year는 있는데 final_semester가 빈 값이면 => final_semester도 disable (DB constraint 피하려면 연도만으로 종료로 판단하거나, 그냥 NULL로 보내는 게 더 맞으면 여기서 disable)
        if (finalSemesterInput && finalSemesterInput.value.trim() === "") {
          finalSemesterInput.disabled = true;
        }
      }

      // initial_year 초기값 비어있으면 안 되니까 기본적으로 required 유지
      // (initial_year/initial_semester은 필수니까 따로 손 안 댐)
    });

    // 이 아래에서 너가 이미 넣어둔 개설/폐지 연도/학기 무효화 로직(교과목 쪽엔 없을 수도 있지만)
    // 그리고 정수 필드 비어있으면 "0" 넣는 로직 등도 같이 들어갈 수 있어.
  });
}

