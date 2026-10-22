/**
 * 구역편성 기초자료(가정별 동정) 수집 — Google Apps Script 웹앱.
 *
 * - 관리자: 구글시트 상단 메뉴 [구역편성 설문] 으로 명단 불러오기, 링크 만들기, 결과 시트 만들기
 * - 구역장: 카톡으로 받은 링크(웹앱 주소?z=토큰)로 접속해 가정별 정보를 확인·작성
 *
 * 웹앱 화면(google.script.run)에서는 이름 끝에 '_'가 없는 전역 함수를 누구나 호출할 수 있으므로,
 * 관리자 함수는 맨 앞에서 requireSheetUi_()로 시트 안에서 실행된 것인지 확인한다.
 */

var CONFIG = {
  SOURCE_SHEET: '2025 구역편성(0905)',
  FAMILY_SHEET: '구역편성_가정',
  ZONE_SHEET: '구역편성_링크',
  RESULT_SHEET: '구역편성_결과',
  TARGET_YEAR: new Date().getFullYear() + 1,
  VILLAGE: '유바디 2마을',
  TZ: 'Asia/Seoul'
};

var ATTENDANCE_LEVELS = [
  ['A', '거의 매번 참석', '구역모임·예배에 꾸준히 참석 (75% 이상)'],
  ['B', '자주 참석', '대체로 참석 (50~75%)'],
  ['C', '가끔 참석', '종종 빠짐 (25~50%)'],
  ['D', '거의 불참', '거의 나오지 못함 (25% 미만)']
];
var NEXT_STATUS = ['구역 배정', '사랑구역', '편성 제외'];
// 원본 시트 '사랑구역' 줄 아래 가정: 구역과 상관없이 나열된 명단이라 구역장 화면과 구역별 집계에서 뺀다
var LOVE_ZONE_ROLE = '사랑구역';

// 구역장에게 보낼 카톡 메시지. 이 글 바로 아래에 구역별 링크가 붙는다.
var KAKAO_MESSAGE = [
  '구역장님, 안녕하세요^^',
  '늘 귀하게 섬겨주셔서 진심으로 감사드립니다.',
  '',
  '내년에 3마을로 올라가시는 가정이 많이 계시기도 하고 새롭게 시작될 구역 편성에 참고하기 위해서 구역장님들께 구역별 모든 가정 현황에 대해 여쭙고자 합니다.',
  '',
  '그리고 구역장님께서 내년 구역장으로 추천하실 가정도 꼭 적어서 보내주시면 감사하겠습니다.',
  '',
  '아래 양식을 보내드리니 이번주 금요일까지 보내주시면 감사드리겠습니다 :)'
].join('\n');

// 구역편성_가정 시트의 열 (순서 = 시트 열 순서)
var FAMILY_FIELDS = [
  ['id', 'ID'], ['zone', '구역'], ['role', '구분'],
  ['husband_name', '형제 이름'], ['husband_birth', '형제 생년'], ['husband_phone', '형제 연락처'],
  ['wife_name', '자매 이름'], ['wife_birth', '자매 생년'], ['wife_phone', '자매 연락처'],
  ['children', '자녀'], ['ref_att_m', '기존 출석(형제)'], ['ref_att_f', '기존 출석(자매)'],
  ['att_2025', '25년 출석률'], ['att_2026', '26년 출석률'], ['sheet_memo', '기존 메모'], ['info_confirmed', '정보 확인'], ['attendance', '출석률(2년)'],
  ['next_status', '내년 배정 의견'], ['recommend_leader', '구역장 추천'],
  ['move_up_target', '3마을 대상(노란색)'], ['move_up', '3마을 이동'], ['note', '동정·특이사항'], ['changed', '수정된 항목'],
  ['updated_at', '작성일시'], ['added', '신규 추가'], ['original', '원본(수정 금지)']
];
var ZONE_FIELDS = [
  ['name', '구역'], ['leader_names', '구역장'], ['link', '링크'], ['total', '가정 수'],
  ['done', '작성 완료'], ['recommended', '구역장 추천 가정'], ['submitted_at', '최종 제출'], ['message', '카톡 메시지'], ['token', '토큰(수정 금지)']
];
var PERSON_LABELS = {
  husband_name: '형제 이름', husband_birth: '형제 생년', husband_phone: '형제 연락처',
  wife_name: '자매 이름', wife_birth: '자매 생년', wife_phone: '자매 연락처'
};

function col_(fields, key) {
  for (var i = 0; i < fields.length; i++) if (fields[i][0] === key) return i;
  throw new Error('unknown field ' + key);
}

function colLetter_(index) {
  var s = '', n = index + 1;
  while (n > 0) { var m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); }
  return s;
}

function now_() {
  return Utilities.formatDate(new Date(), CONFIG.TZ, 'yyyy-MM-dd HH:mm');
}

/** 사용자가 입력한 글자가 수식으로 해석되지 않게 한다. */
function safe_(v) {
  var s = String(v === null || v === undefined ? '' : v);
  return /^[=+\-@]/.test(s) ? "'" + s : s;
}

function sheet_(name) {
  return SpreadsheetApp.getActive().getSheetByName(name);
}

// ------------------------------------------------------------------ 관리자 메뉴

function onOpen() {
  try { refreshZoneFormulas_(); } catch (e) {}
  SpreadsheetApp.getUi().createMenu('구역편성 설문')
    .addItem('1. 명단 불러오기 (최초 1회)', 'setupFromSource')
    .addItem('2. 구역장 링크·카톡 메시지 만들기', 'buildLinks')
    .addItem('카톡 메시지 복사하기', 'showMessages')
    .addItem('출석 기록 불러오기 (25·26년)', 'importAttendance')
    .addSeparator()
    .addItem('3. 결과 시트 만들기 (1마을 형식)', 'buildResult')
    .addToUi();
}

function requireSheetUi_() {
  try {
    return SpreadsheetApp.getUi();
  } catch (e) {
    throw new Error('시트 메뉴에서만 실행할 수 있습니다.');
  }
}

function setupFromSource() {
  var ui = requireSheetUi_();
  var ss = SpreadsheetApp.getActive();
  var source = ss.getSheetByName(CONFIG.SOURCE_SHEET);
  if (!source) return ui.alert("'" + CONFIG.SOURCE_SHEET + "' 시트를 찾지 못했습니다.");

  var existing = sheet_(CONFIG.FAMILY_SHEET);
  if (existing && existing.getLastRow() > 1) {
    var written = existing.getRange(2, col_(FAMILY_FIELDS, 'updated_at') + 1, existing.getLastRow() - 1, 1)
      .getValues().filter(function (r) { return r[0]; }).length;
    var msg = written
      ? '⚠️ 구역장님들이 이미 ' + written + '가정을 작성했습니다.\n다시 불러오면 작성 내용과 링크가 모두 지워집니다. 계속할까요?'
      : '이미 불러온 명단이 있습니다. 지우고 새로 불러올까요? (구역별 링크도 새로 만들어집니다)';
    if (ui.alert('명단 다시 불러오기', msg, ui.ButtonSet.YES_NO) !== ui.Button.YES) return;
  }

  var range = source.getDataRange();
  var zones = parseSourceRows_(range.getValues(), range.getBackgrounds());

  var famRows = [], zoneRows = [], n = 0;
  zones.forEach(function (z) {
    z.families.forEach(function (f) {
      n++;
      var original = {
        husband_name: f.husband_name, husband_birth: f.husband_birth, husband_phone: f.husband_phone,
        wife_name: f.wife_name, wife_birth: f.wife_birth, wife_phone: f.wife_phone,
        children: formatChildren_(f.children)
      };
      var rec = {
        id: 'F' + ('000' + n).slice(-4), zone: z.name, role: f.role,
        children: original.children, original: JSON.stringify(original), added: '',
        move_up_target: f.move_up ? 'Y' : '', move_up: f.move_up ? '✓' : ''
      };
      ['husband_name', 'husband_birth', 'husband_phone', 'wife_name', 'wife_birth', 'wife_phone',
        'ref_att_m', 'ref_att_f', 'sheet_memo'].forEach(function (k) { rec[k] = f[k]; });
      famRows.push(FAMILY_FIELDS.map(function (fd) { return safe_(rec[fd[0]]); }));
    });
    zoneRows.push({ name: z.name, leader_names: z.leader_names, token: newToken_() });
  });

  var famSheet = resetSheet_(CONFIG.FAMILY_SHEET, FAMILY_FIELDS);
  if (famRows.length) famSheet.getRange(2, 1, famRows.length, FAMILY_FIELDS.length).setValues(famRows);
  formatFamilySheet_(famSheet);

  var zoneSheet = resetSheet_(CONFIG.ZONE_SHEET, ZONE_FIELDS);
  writeZoneRows_(zoneSheet, zoneRows);

  var attNote = '';
  try { fillAttendanceHistory_(); } catch (e) {
    attNote = '\n(25·26년 출석 기록은 불러오지 못했습니다: ' + e.message + ' → 메뉴 [출석 기록 불러오기]로 다시 시도)';
  }

  var moving = zones.reduce(function (sum, z) {
    return sum + z.families.filter(function (f) { return f.move_up; }).length;
  }, 0);
  var done = '완료: ' + zones.length + '개 구역, ' + n + '가정을 불러왔습니다. (3마을 이동 대상 ' + moving + '가정)' + attNote + '\n\n';
  var url = webappUrl_();
  if (url) {
    writeLinks_(zoneSheet, url);
    ui.alert(done + '구역별 링크와 카톡 메시지도 만들었습니다. 메뉴 [카톡 메시지 복사하기]에서 구역별로 복사해 보내주세요.');
  } else {
    ui.alert(done + '다음 단계: [배포 > 새 배포 > 웹 앱]으로 배포한 뒤, 메뉴 [2. 구역장 링크·카톡 메시지 만들기]를 눌러주세요.');
  }
}

function newToken_() {
  return Utilities.getUuid().replace(/-/g, '').slice(0, 12);
}

function resetSheet_(name, fields) {
  var ss = SpreadsheetApp.getActive();
  var sh = ss.getSheetByName(name);
  if (sh) sh.clear(); else sh = ss.insertSheet(name);
  sh.getRange(1, 1, sh.getMaxRows(), fields.length).setNumberFormat('@');
  sh.getRange(1, 1, 1, fields.length).setValues([fields.map(function (f) { return f[1]; })])
    .setFontWeight('bold').setBackground('#e8eef7');
  sh.setFrozenRows(1);
  return sh;
}

/**
 * 25·26년 출석률 열이 생기기 전에 만든 가정 시트면 '기존 출석(자매)' 뒤에 두 열을 끼워 넣는다.
 * (열을 끼워 넣으면 구역편성_링크 시트의 수식도 시트가 알아서 고쳐준다)
 */
function ensureFamilyColumns_() {
  var sh = sheet_(CONFIG.FAMILY_SHEET);
  if (!sh || sh.getLastColumn() < 1) return;
  var c25 = col_(FAMILY_FIELDS, 'att_2025');
  var label = function () { return String(sh.getRange(1, c25 + 1).getValue()); };
  if (label() === FAMILY_FIELDS[c25][1]) return;
  withLock_(function () {
    if (label() === FAMILY_FIELDS[c25][1]) return;
    var prev = FAMILY_FIELDS[c25 - 1][1];
    if (String(sh.getRange(1, c25).getValue()) !== prev) throw new Error("가정 시트 머리글이 예상과 다릅니다 ('" + prev + "' 열을 찾지 못함).");
    sh.insertColumnsAfter(c25, 2);
    sh.getRange(1, c25 + 1, sh.getMaxRows(), 2).setNumberFormat('@');
    sh.getRange(1, c25 + 1, 1, 2).setValues([[FAMILY_FIELDS[c25][1], FAMILY_FIELDS[c25 + 1][1]]])
      .setFontWeight('bold').setBackground('#e8eef7');
    sh.setColumnWidths(c25 + 1, 2, 200);
  });
}

function formatFamilySheet_(sh) {
  var widths = { id: 60, zone: 60, role: 60, children: 220, att_2025: 200, att_2026: 200, sheet_memo: 200, note: 360, changed: 120, original: 80 };
  FAMILY_FIELDS.forEach(function (f, i) { if (widths[f[0]]) sh.setColumnWidth(i + 1, widths[f[0]]); });
  sh.setFrozenColumns(3);
  sh.getRange(2, col_(FAMILY_FIELDS, 'note') + 1, sh.getMaxRows() - 1, 1).setWrap(true);
}

/** 구역 행 쓰기. 가정 수·작성 완료는 가정 시트를 세는 수식이라 실시간으로 바뀐다. */
function writeZoneRows_(sh, zoneRows) {
  var rows = zoneRows.map(function (z) {
    var rec = { name: z.name, leader_names: z.leader_names, link: '', submitted_at: '', message: '', token: z.token };
    return ZONE_FIELDS.map(function (f) { return rec[f[0]] === undefined ? '' : rec[f[0]]; });
  });
  if (!rows.length) return;
  sh.getRange(2, 1, rows.length, ZONE_FIELDS.length).setValues(rows);
  writeZoneFormulas_(sh, rows.length);
  sh.setColumnWidth(col_(ZONE_FIELDS, 'link') + 1, 320);
  sh.setColumnWidth(col_(ZONE_FIELDS, 'message') + 1, 360);
}

/** 가정 수·작성 완료·구역장 추천 수식 (사랑구역 가정은 세지 않는다) */
function writeZoneFormulas_(sh, n) {
  var L = function (k) { return colLetter_(col_(FAMILY_FIELDS, k)); };
  var ref = "'" + CONFIG.FAMILY_SHEET + "'!";
  var rg = function (k) { return ref + L(k) + ':' + L(k); };
  var notLove = rg('role') + ',"<>' + LOVE_ZONE_ROLE + '"';
  var formulas = { total: [], done: [], recommended: [] };
  for (var r = 2; r < n + 2; r++) {
    formulas.total.push(['=COUNTIFS(' + rg('zone') + ',A' + r + ',' + notLove + ')']);
    formulas.done.push(['=COUNTIFS(' + rg('zone') + ',A' + r + ',' + notLove + ',' + rg('info_confirmed') + ',"✓",' +
      rg('attendance') + ',"?*")']);
    formulas.recommended.push(['=IFERROR(TEXTJOIN(", ",TRUE,ARRAYFORMULA(REGEXREPLACE(FILTER(' +
      rg('husband_name') + '&" · "&' + rg('wife_name') + ',' + rg('zone') + '=A' + r + ',' +
      rg('recommend_leader') + '="✓",' + rg('role') + '<>"' + LOVE_ZONE_ROLE + '"),"^ · | · $",""))),"")']);
  }
  // 일반 텍스트(@) 서식 칸에 넣으면 수식이 글자로 저장되므로 서식을 먼저 바꾼다
  Object.keys(formulas).forEach(function (k) {
    sh.getRange(2, col_(ZONE_FIELDS, k) + 1, n, 1).setNumberFormat(k === 'recommended' ? 'General' : '0')
      .setFormulas(formulas[k]);
  });
}

/** 사랑구역을 빼기 전에 만든 구역 시트면 수식을 새로 쓴다. */
function refreshZoneFormulas_() {
  var sh = sheet_(CONFIG.ZONE_SHEET);
  if (!sh || sh.getLastRow() < 2) return;
  if (String(sh.getRange(2, col_(ZONE_FIELDS, 'total') + 1).getFormula()).indexOf(LOVE_ZONE_ROLE) >= 0) return;
  writeZoneFormulas_(sh, sh.getLastRow() - 1);
}

function buildLinks() {
  var ui = requireSheetUi_();
  var sh = sheet_(CONFIG.ZONE_SHEET);
  if (!sh || sh.getLastRow() < 2) return ui.alert('먼저 [1. 명단 불러오기]를 실행해주세요.');

  var url = webappUrl_();
  if (!url) {
    var res = ui.prompt('웹앱 주소', '[배포 > 배포 관리]에 있는 웹 앱 URL(…/exec)을 붙여넣어 주세요.', ui.ButtonSet.OK_CANCEL);
    if (res.getSelectedButton() !== ui.Button.OK) return;
    url = res.getResponseText().trim();
    if (!/^https:\/\/script\.google\.com\/.+\/exec$/.test(url)) {
      return ui.alert('주소가 올바르지 않습니다. https://script.google.com/…/exec 형태여야 합니다.');
    }
    PropertiesService.getScriptProperties().setProperty('WEBAPP_URL', url);
  }
  writeLinks_(sh, url);
  showMessages();
}

/** deploy.sh가 Deployment.gs에 적어 둔 주소 → 직접 입력한 주소 순으로 쓴다. */
function webappUrl_() {
  if (typeof DEPLOYED_WEBAPP_URL !== 'undefined' && DEPLOYED_WEBAPP_URL) return DEPLOYED_WEBAPP_URL;
  return PropertiesService.getScriptProperties().getProperty('WEBAPP_URL') || '';
}

function writeLinks_(sh, url) {
  var n = sh.getLastRow() - 1;
  var data = sh.getRange(2, 1, n, ZONE_FIELDS.length).getValues();
  var out = data.map(function (r) {
    var link = url + '?z=' + r[col_(ZONE_FIELDS, 'token')];
    return [link, KAKAO_MESSAGE + '\n\n' + link];
  });
  sh.getRange(2, col_(ZONE_FIELDS, 'link') + 1, n, 1).setValues(out.map(function (o) { return [o[0]]; }));
  sh.getRange(2, col_(ZONE_FIELDS, 'message') + 1, n, 1).setValues(out.map(function (o) { return [o[1]]; }))
    .setWrap(true).setVerticalAlignment('top');
}

/**
 * 구역별 카톡 메시지를 복사 버튼과 함께 보여준다.
 * (시트 칸을 그대로 복사하면 줄바꿈 때문에 메시지 앞뒤에 따옴표가 붙어서 따로 창을 띄운다)
 */
function showMessages() {
  var ui = requireSheetUi_();
  var sh = sheet_(CONFIG.ZONE_SHEET);
  if (!sh || sh.getLastRow() < 2) return ui.alert('먼저 [1. 명단 불러오기]를 실행해주세요.');
  var zones = sh.getRange(2, 1, sh.getLastRow() - 1, ZONE_FIELDS.length).getValues().map(function (r) {
    return {
      name: String(r[col_(ZONE_FIELDS, 'name')]), leaders: String(r[col_(ZONE_FIELDS, 'leader_names')]),
      message: String(r[col_(ZONE_FIELDS, 'message')])
    };
  });
  if (!zones.some(function (z) { return z.message; })) {
    return ui.alert('아직 링크가 없습니다. 메뉴 [2. 구역장 링크·카톡 메시지 만들기]를 먼저 눌러주세요.');
  }
  var t = HtmlService.createTemplateFromFile('Messages');
  t.payload = JSON.stringify(zones).replace(/</g, '\\u003c');
  ui.showModalDialog(t.evaluate().setWidth(560).setHeight(640), '구역별 카톡 메시지');
}

/** '1마을 올라오는 가정 정리'와 같은 형식(가정당 2줄, 병합)으로 결과 시트를 만든다. */
function buildResult() {
  var ui = requireSheetUi_();
  ensureFamilyColumns_();
  var families = readFamilies_().filter(function (f) { return f.role !== LOVE_ZONE_ROLE; });
  if (!families.length) return ui.alert('먼저 [1. 명단 불러오기]를 실행해주세요.');

  var headers = ['NO', '현재 구역', '이름', '생년월일', '자녀', '출석률', '동정', '내년 배정 의견', '구역장 추천',
    '3마을 이동', '정보 수정', '구분'];
  var ss = SpreadsheetApp.getActive();
  var sh = ss.getSheetByName(CONFIG.RESULT_SHEET);
  if (sh) { sh.getRange(1, 1, sh.getMaxRows(), sh.getMaxColumns()).breakApart(); sh.clear(); }
  else sh = ss.insertSheet(CONFIG.RESULT_SHEET);

  var rows = [], merges = [];
  families.forEach(function (f, i) {
    var start = rows.length + 3;  // 1행 비움, 2행 머리글 (원본 시트와 같은 위치)
    var people = [[f.husband_name, f.husband_birth], [f.wife_name, f.wife_birth]]
      .filter(function (p) { return p[0]; });
    if (!people.length) people = [['', '']];
    people.forEach(function (p, j) {
      rows.push(j === 0
        ? [i + 1, f.zone, p[0], p[1], f.children, f.attendance, f.note, f.next_status, f.recommend_leader,
          f.move_up, f.changed, f.role]
        : ['', '', p[0], p[1], '', '', '', '', '', '', '', '']);
    });
    if (people.length > 1) merges.push(start);
  });

  sh.getRange(2, 2, 1, headers.length).setValues([headers]).setFontWeight('bold').setBackground('#e8eef7')
    .setHorizontalAlignment('center');
  var body = sh.getRange(3, 2, rows.length, headers.length);
  body.setNumberFormat('@').setValues(rows.map(function (r) { return r.map(safe_); }))
    .setVerticalAlignment('middle').setWrap(true);
  body.setBorder(true, true, true, true, true, true, '#d0d4da', SpreadsheetApp.BorderStyle.SOLID);
  sh.getRange(2, 2, 1, headers.length).setBorder(true, true, true, true, true, true);
  merges.forEach(function (r) {
    [1, 2, 5, 6, 7, 8, 9, 10, 11, 12].forEach(function (c) { sh.getRange(r, c + 1, 2, 1).merge(); });
  });
  [40, 70, 70, 90, 200, 60, 420, 100, 80, 80, 120, 70].forEach(function (w, i) { sh.setColumnWidth(i + 2, w); });
  sh.setColumnWidth(1, 20);
  sh.getRange(3, 2, rows.length, 2).setHorizontalAlignment('center');
  sh.getRange(3, 7, rows.length, 1).setHorizontalAlignment('center');
  sh.getRange(3, 10, rows.length, 2).setHorizontalAlignment('center');
  sh.setFrozenRows(2);
  ss.setActiveSheet(sh);
  ui.alert('결과 시트를 만들었습니다: ' + families.length + '가정');
}

// ------------------------------------------------------------------ 데이터 읽기/쓰기

function readFamilies_() {
  var sh = sheet_(CONFIG.FAMILY_SHEET);
  if (!sh || sh.getLastRow() < 2) return [];
  return sh.getRange(2, 1, sh.getLastRow() - 1, FAMILY_FIELDS.length).getValues().map(rowToFamily_)
    .filter(function (f) { return f.id; });
}

function rowToFamily_(row) {
  var f = {};
  FAMILY_FIELDS.forEach(function (fd, i) { f[fd[0]] = String(row[i] === null ? '' : row[i]); });
  return f;
}

function findZoneByToken_(token) {
  var sh = sheet_(CONFIG.ZONE_SHEET);
  if (!token || !sh || sh.getLastRow() < 2) return null;
  var data = sh.getRange(2, 1, sh.getLastRow() - 1, ZONE_FIELDS.length).getValues();
  for (var i = 0; i < data.length; i++) {
    if (String(data[i][col_(ZONE_FIELDS, 'token')]) === String(token)) {
      return {
        row: i + 2, name: String(data[i][col_(ZONE_FIELDS, 'name')]),
        leader_names: String(data[i][col_(ZONE_FIELDS, 'leader_names')]),
        submitted_at: String(data[i][col_(ZONE_FIELDS, 'submitted_at')] || '')
      };
    }
  }
  return null;
}

function requireZone_(token) {
  var zone = findZoneByToken_(token);
  if (!zone) throw new Error('링크가 올바르지 않습니다. 관리자에게 문의해주세요.');
  return zone;
}

/** 가정 ID로 시트 행 번호를 찾는다. 다른 구역의 가정이면 null. */
function findFamilyRow_(zoneName, id) {
  var sh = sheet_(CONFIG.FAMILY_SHEET);
  var cell = sh.getRange(2, 1, Math.max(sh.getLastRow() - 1, 1), 1).createTextFinder(String(id))
    .matchEntireCell(true).findNext();
  if (!cell) return null;
  var row = cell.getRow();
  var zone = sh.getRange(row, col_(FAMILY_FIELDS, 'zone') + 1).getValue();
  var role = sh.getRange(row, col_(FAMILY_FIELDS, 'role') + 1).getValue();
  return String(zone) === zoneName && String(role) !== LOVE_ZONE_ROLE ? row : null;
}

/** 화면에 보낼 가정 정보 */
function familyView_(f) {
  return {
    id: f.id, role: f.role, added: f.added === 'Y',
    husband_name: f.husband_name, husband_birth: f.husband_birth, husband_phone: f.husband_phone,
    wife_name: f.wife_name, wife_birth: f.wife_birth, wife_phone: f.wife_phone,
    children: parseChildren_(f.children), att_2025: f.att_2025, att_2026: f.att_2026,
    info_confirmed: f.info_confirmed === '✓', attendance: f.attendance, next_status: f.next_status,
    recommend_leader: f.recommend_leader === '✓', move_up_target: f.move_up_target === 'Y', move_up: f.move_up === '✓',
    note: f.note, updated_at: f.updated_at
  };
}

function changedFields_(f, original) {
  if (!original) return '';
  var o;
  try { o = JSON.parse(original); } catch (e) { return ''; }
  var out = [];
  Object.keys(PERSON_LABELS).forEach(function (k) {
    if ((f[k] || '') !== (o[k] || '')) out.push(PERSON_LABELS[k]);
  });
  if ((f.children || '') !== (o.children || '')) out.push('자녀');
  return out.join(', ');
}

function clip_(v, n) {
  return String(v === null || v === undefined ? '' : v).trim().slice(0, n || 40);
}

function withLock_(fn) {
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try { return fn(); } finally { lock.releaseLock(); }
}

// ------------------------------------------------------------------ 웹앱 (구역장 화면)

function doGet(e) {
  var token = e && e.parameter && e.parameter.z;
  var zone = findZoneByToken_(token);
  var out;
  if (!zone) {
    out = HtmlService.createHtmlOutput(
      '<div style="font-family:sans-serif;padding:40px 20px;text-align:center;color:#555">' +
      '링크가 올바르지 않습니다.<br>카톡으로 받은 주소 전체를 다시 눌러주세요.</div>');
  } else {
    ensureFamilyColumns_();
    refreshZoneFormulas_();
    var t = HtmlService.createTemplateFromFile('Leader');
    t.payload = JSON.stringify(getZonePayload_(zone, token)).replace(/</g, '\\u003c');
    out = t.evaluate();
  }
  return out.setTitle((zone ? zone.name + ' · ' : '') + CONFIG.TARGET_YEAR + ' 구역편성 기초자료')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

function getZonePayload_(zone, token) {
  var families = readFamilies_().filter(function (f) {
    return f.zone === zone.name && f.role !== LOVE_ZONE_ROLE;
  }).map(familyView_);
  return {
    token: token, zone: zone.name, leader_names: zone.leader_names, submitted_at: zone.submitted_at,
    year: CONFIG.TARGET_YEAR, village: CONFIG.VILLAGE,
    levels: ATTENDANCE_LEVELS, next_status: NEXT_STATUS, families: families
  };
}

function apiSaveFamily(token, id, data) {
  var zone = requireZone_(token);
  ensureFamilyColumns_();
  data = data || {};
  return withLock_(function () {
    var row = findFamilyRow_(zone.name, id);
    if (!row) throw new Error('가정을 찾지 못했습니다. 화면을 새로고침 해주세요.');
    var sh = sheet_(CONFIG.FAMILY_SHEET);
    var range = sh.getRange(row, 1, 1, FAMILY_FIELDS.length);
    var f = rowToFamily_(range.getValues()[0]);

    Object.keys(PERSON_LABELS).forEach(function (k) { f[k] = clip_(data[k], 20); });
    f.children = formatChildren_((data.children || []).map(function (c) {
      return {
        name: clip_(c.name, 30).replace(/[(),]/g, ''), year: clip_(c.year, 4).replace(/[(),]/g, ''),
        gender: c.gender === '남' || c.gender === '여' ? c.gender : '', note: clip_(c.note, 50).replace(/[(),]/g, ' ')
      };
    }).filter(function (c) { return c.name; }));
    f.info_confirmed = data.info_confirmed ? '✓' : '';
    f.attendance = ['A', 'B', 'C', 'D'].indexOf(data.attendance) >= 0 ? data.attendance : '';
    f.next_status = NEXT_STATUS.indexOf(data.next_status) >= 0 ? data.next_status : '';
    f.recommend_leader = data.recommend_leader ? '✓' : '';
    f.move_up = f.move_up_target === 'Y' && data.move_up ? '✓' : '';
    f.note = clip_(data.note, 3000);
    f.changed = f.added === 'Y' ? '신규 추가' : changedFields_(f, f.original);
    f.updated_at = now_();

    range.setValues([FAMILY_FIELDS.map(function (fd) { return safe_(f[fd[0]]); })]);
    return familyView_(f);
  });
}

function apiAddFamily(token) {
  var zone = requireZone_(token);
  ensureFamilyColumns_();
  return withLock_(function () {
    var sh = sheet_(CONFIG.FAMILY_SHEET);
    var ids = sh.getRange(2, 1, Math.max(sh.getLastRow() - 1, 1), 1).getValues();
    var max = 0;
    ids.forEach(function (r) { var n = parseInt(String(r[0]).slice(1), 10); if (n > max) max = n; });
    var f = { id: 'F' + ('000' + (max + 1)).slice(-4), zone: zone.name, role: '신규 추가', added: 'Y' };
    sh.appendRow(FAMILY_FIELDS.map(function (fd) { return f[fd[0]] || ''; }));
    return familyView_(rowToFamily_(FAMILY_FIELDS.map(function (fd) { return f[fd[0]] || ''; })));
  });
}

/** 구역장이 직접 추가한 가정만 지울 수 있다. 명단의 가정은 '편성 제외'로 표시한다. */
function apiDeleteFamily(token, id) {
  var zone = requireZone_(token);
  ensureFamilyColumns_();
  return withLock_(function () {
    var row = findFamilyRow_(zone.name, id);
    if (!row) return true;
    var sh = sheet_(CONFIG.FAMILY_SHEET);
    if (sh.getRange(row, col_(FAMILY_FIELDS, 'added') + 1).getValue() !== 'Y') {
      throw new Error('명단에 있던 가정은 삭제할 수 없어요. 내년 배정 의견에서 "편성 제외"를 골라주세요.');
    }
    sh.deleteRow(row);
    return true;
  });
}

function apiSubmit(token) {
  var zone = requireZone_(token);
  var at = now_();
  sheet_(CONFIG.ZONE_SHEET).getRange(zone.row, col_(ZONE_FIELDS, 'submitted_at') + 1).setValue(at);
  return at;
}
