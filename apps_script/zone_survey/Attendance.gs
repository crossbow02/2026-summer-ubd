/**
 * 기존 출석 기록(25년 상반기 개인별 출석률, 26년 주차별 출석부)을 읽어
 * 구역편성_가정 시트의 '25년 출석률', '26년 출석률' 칸을 채운다.
 *
 * - 25년: '25 상반기 개인별 출석률' 시트의 출석횟수 / 총구역모임 수
 * - 26년: 날짜 이름(예: 0315) 시트마다 구역별 출석자를 모아, 그 사람 구역이 모임한 주 중 출석한 주의 비율
 *   (모임없음·미제출·공식 휴무 주는 빼고 센다)
 */

var ATTENDANCE_SOURCES = {
  Y2025: { id: '168eb9C1gDEHQ5gNpIe1h8XwTUUv2rsufvuLtpfrCeJo', sheet: '25 상반기 개인별 출석률' },
  Y2026: { id: '1sXRrDbhbZUa0iSKFh4F7CEF5BIANmAASr17TJOa1c2s', sheetPattern: /^\d{4}$/ }
};

/** '01구역(김민웅,김혜영)', '1구역', '18임원구역', '임원' -> '1' | '임원' */
function zoneKey_(s) {
  s = String(s || '');
  if (s.indexOf('임원') >= 0) return '임원';
  var m = s.match(/^\s*0*(\d+)/);
  if (!m) return '';
  return m[1] === '18' ? '임원' : m[1];
}

/** '장지연(박성욱 형제 아내)' -> '장지연' */
function cleanName_(s) {
  return String(s || '').replace(/\(.*?\)/g, '').replace(/\s+/g, '');
}

/** 동명이인 구분 글자 제거: '김수연B' -> '김수연' */
function baseName_(s) {
  return cleanName_(s).replace(/[A-Z]$/, '');
}

function pctText_(count, total) {
  return Math.round(count / total * 100) + '% (' + count + '/' + total + '회)';
}

// ------------------------------------------------------------------ 25년

function read2025_() {
  var src = ATTENDANCE_SOURCES.Y2025;
  var sh = SpreadsheetApp.openById(src.id).getSheetByName(src.sheet);
  if (!sh) throw new Error("25년 출석 시트 '" + src.sheet + "'를 찾지 못했습니다.");
  var rows = sh.getDataRange().getValues();
  var h = rows[0].map(function (v) { return String(v).trim(); });
  var ci = {
    zone: h.indexOf('구역'), gender: h.indexOf('성별'), name: h.indexOf('이름'),
    count: h.indexOf('출석횟수'), meets: h.indexOf('총구역모임 수')
  };
  if (ci.name < 0 || ci.count < 0 || ci.meets < 0) throw new Error('25년 출석 시트의 머리글이 예상과 다릅니다.');
  var out = [];
  rows.slice(1).forEach(function (r) {
    var name = cleanName_(r[ci.name]);
    var count = Number(r[ci.count]), meets = Number(r[ci.meets]);
    if (!name || !(meets > 0) || isNaN(count)) return;
    out.push({ zone: zoneKey_(r[ci.zone]), gender: String(r[ci.gender]).trim(), name: name, count: count, meets: meets });
  });
  return out;
}

function lookup2025_(records, name, gender, zone) {
  name = cleanName_(name);
  var c = records.filter(function (x) { return x.name === name; });
  if (!c.length) c = records.filter(function (x) { return baseName_(x.name) === baseName_(name); });
  var g = c.filter(function (x) { return x.gender === gender; });
  if (g.length) c = g;
  var z = c.filter(function (x) { return x.zone === zone; });
  if (z.length) c = z;
  return c[0] || null;
}

// ------------------------------------------------------------------ 26년

/** -> { held: {zone: 모임 주 수}, attended: {zone: {이름: 출석 주 수}}, weeks: [시트 이름] } */
function read2026_() {
  var ss = SpreadsheetApp.openById(ATTENDANCE_SOURCES.Y2026.id);
  var held = {}, seen = {}, weeks = [];
  var mark = function (wk, zone, names) {
    if (!zone || !names.length) return;
    held[zone] = held[zone] || {};
    held[zone][wk] = true;
    seen[zone] = seen[zone] || {};
    names.forEach(function (n) {
      seen[zone][n] = seen[zone][n] || {};
      seen[zone][n][wk] = true;
    });
  };
  ss.getSheets().forEach(function (sh) {
    var wk = sh.getName();
    if (!ATTENDANCE_SOURCES.Y2026.sheetPattern.test(wk)) return;
    var rows = sh.getDataRange().getValues();
    if (!rows.length) return;
    weeks.push(wk);
    if (String(rows[0][0]).trim() === '타임스탬프') {
      // 구글 설문 응답 형식: B열 구역, '출석부' 머리글 칸부터 오른쪽으로 출석자 이름
      var start = rows[0].map(function (v) { return String(v).trim(); }).indexOf('출석부');
      if (start < 0) return;
      rows.slice(1).forEach(function (r) {
        mark(wk, zoneKey_(r[1]), r.slice(start).map(cleanName_).filter(String));
      });
      return;
    }
    // 웹 설문 출석부 형식: '번호|구역|상태|…|출석자 (쉼표로 구분…)' 표, 상태가 '모임'인 구역만
    for (var i = 0; i < rows.length; i++) {
      if (String(rows[i][0]).trim() !== '번호' || String(rows[i][1]).trim() !== '구역') continue;
      var h = rows[i].map(function (v) { return String(v).trim(); });
      var cs = h.indexOf('상태'), ca = -1;
      h.forEach(function (v, j) { if (ca < 0 && v.indexOf('출석자') === 0) ca = j; });
      if (cs < 0 || ca < 0) return;
      for (var r = i + 1; r < rows.length && String(rows[r][0]).trim(); r++) {
        if (String(rows[r][cs]).trim() !== '모임') continue;
        mark(wk, zoneKey_(rows[r][1]), String(rows[r][ca]).split(',').map(cleanName_).filter(String));
      }
      return;
    }
  });
  var count = function (o) { return Object.keys(o || {}).length; };
  var out = { held: {}, attended: {}, weeks: weeks.sort() };
  Object.keys(held).forEach(function (z) { out.held[z] = count(held[z]); });
  Object.keys(seen).forEach(function (z) {
    out.attended[z] = {};
    Object.keys(seen[z]).forEach(function (n) { out.attended[z][n] = count(seen[z][n]); });
  });
  return out;
}

/** 자기 구역 출석부에서만 찾는다. 이름이 없으면 한 번도 출석하지 않은 것. */
function lookup2026_(data, name, zone) {
  var total = data.held[zone] || 0;
  if (!total) return null;
  var names = data.attended[zone] || {};
  name = cleanName_(name);
  var count = names[name];
  if (count === undefined) {
    var same = Object.keys(names).filter(function (n) { return baseName_(n) === baseName_(name); });
    count = same.length === 1 ? names[same[0]] : 0;
  }
  return { count: count, total: total };
}

// ------------------------------------------------------------------ 시트에 쓰기

function familyAttendanceTexts_(f, rec25, data26) {
  var zone = zoneKey_(f.zone);
  var people = [['형제', f.husband_name, '남'], ['자매', f.wife_name, '여']].filter(function (p) { return p[1]; });
  var t25 = people.map(function (p) {
    var r = lookup2025_(rec25, p[1], p[2], zone);
    return p[0] + ' ' + (r ? pctText_(r.count, r.meets) : '기록 없음');
  });
  var t26 = people.map(function (p) {
    var r = lookup2026_(data26, p[1], zone);
    return p[0] + ' ' + (r ? pctText_(r.count, r.total) : '기록 없음');
  });
  return [t25.join(' · '), t26.join(' · ')];
}

/** 가정 시트의 25·26년 출석률 칸을 모두 다시 채운다. 다른 칸은 건드리지 않는다. */
function fillAttendanceHistory_() {
  ensureFamilyColumns_();
  var rec25 = read2025_();
  var data26 = read2026_();
  return withLock_(function () {
    var sh = sheet_(CONFIG.FAMILY_SHEET);
    if (!sh || sh.getLastRow() < 2) return { families: 0, weeks: data26.weeks };
    var n = sh.getLastRow() - 1;
    var values = sh.getRange(2, 1, n, FAMILY_FIELDS.length).getValues();
    var out = values.map(function (row) {
      var f = rowToFamily_(row);
      return f.id ? familyAttendanceTexts_(f, rec25, data26) : ['', ''];
    });
    var c25 = col_(FAMILY_FIELDS, 'att_2025');
    if (col_(FAMILY_FIELDS, 'att_2026') !== c25 + 1) throw new Error('att_2025/att_2026 열이 붙어 있어야 합니다.');
    sh.getRange(2, c25 + 1, n, 2).setNumberFormat('@').setValues(out);
    return { families: out.filter(function (o) { return o[0] || o[1]; }).length, weeks: data26.weeks };
  });
}

function importAttendance() {
  var ui = requireSheetUi_();
  if (!sheet_(CONFIG.FAMILY_SHEET)) return ui.alert('먼저 [1. 명단 불러오기]를 실행해주세요.');
  var res = fillAttendanceHistory_();
  var w = res.weeks;
  ui.alert('출석 기록을 불러왔습니다: ' + res.families + '가정\n' +
    '· 25년: 상반기 개인별 출석률 (출석횟수 / 구역모임 수)\n' +
    '· 26년: 출석부 ' + w.length + '주 (' + (w[0] || '') + '~' + (w[w.length - 1] || '') + '), 구역이 모임한 주 기준\n\n' +
    '새 출석부가 쌓이면 이 메뉴를 다시 누르면 26년 출석률이 갱신됩니다.');
}
