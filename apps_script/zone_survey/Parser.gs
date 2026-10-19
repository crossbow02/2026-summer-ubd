/**
 * '2025 구역편성(0905)' 시트 파서.
 * 시트는 구역이 열(C~), 가정이 세로 블록(이름/전화번호/이름/전화번호/자녀/남 출석/여 출석/메모)으로 되어 있다.
 * 함수 이름 끝의 '_'는 웹앱(google.script.run)에서 호출되지 않도록 하는 비공개 표시.
 */

var PHONE_RE_ = /^0\d{1,2}-?\d{3,4}-?\d{4}$/;
var PERSON_RE_ = /^\s*([가-힣A-Za-z]+[A-Z]?)\s*(?:\((\d{2})\))?\s*$/;
var CHILD_RE_ = /([가-힣A-Za-z]+)\s*\(([^)]*)\)/g;
var GRADE_RE_ = /^\s*([A-D])\s*$/;
var POSITIONAL_ = ['이름', '전화번호', '이름', '전화번호', '자녀'];
// 자녀 칸이 이 색이면 내년에 3마을로 올라가는 가정 (연한 노랑은 구역장 줄 표시라 제외)
var MOVE_UP_COLORS_ = ['#ffff00'];

function isMoveUpColor_(bg) {
  return MOVE_UP_COLORS_.indexOf(String(bg || '').toLowerCase()) >= 0;
}

function s_(v) {
  if (v === null || v === undefined) return '';
  if (v instanceof Date) return v.getFullYear() + '-' + (v.getMonth() + 1) + '-' + v.getDate();
  return String(v).trim();
}

function isPhone_(v) {
  return PHONE_RE_.test(s_(v));
}

function looksLikeChildren_(v) {
  var s = s_(v);
  return /\([^)]*(남|여)/.test(s) || s.indexOf('자녀') >= 0;
}

function expandYear_(yy) {
  var n = parseInt(yy, 10);
  return String(n > 30 ? 1900 + n : 2000 + n);
}

/** '김민웅(86)' -> ['김민웅', '1986'] */
function parsePerson_(v) {
  var s = s_(v);
  var m = s.match(PERSON_RE_);
  if (!m) return [s, ''];
  return [m[1], m[2] ? expandYear_(m[2]) : ''];
}

/** '김다윤(17,남) 김하윤(19,여)' -> [{name, year, gender, note}] */
function parseChildren_(text) {
  var s = s_(text);
  if (!s || s.replace(/ /g, '').indexOf('없음') >= 0 || s === '0') return [];
  var children = [];
  var m;
  CHILD_RE_.lastIndex = 0;
  while ((m = CHILD_RE_.exec(s)) !== null) {
    var year = '', gender = '', notes = [];
    m[2].split(/[,./\s]+/).forEach(function (tok) {
      if (!tok) return;
      if (/^\d{2}$/.test(tok)) year = tok;
      else if (tok === '남' || tok === '여') gender = tok;
      else notes.push(tok);
    });
    children.push({ name: m[1], year: year, gender: gender, note: notes.join(' ') });
  }
  if (!children.length) children.push({ name: s, year: '', gender: '', note: '' });
  return children;
}

/** 자녀 목록 -> 시트에 저장하는 글자 형식 '김다윤(17,남), 김하윤(19,여)' */
function formatChildren_(children) {
  return (children || []).map(function (c) {
    var inner = [c.year, c.gender, c.note].filter(function (x) { return x; }).join(',');
    return inner ? c.name + '(' + inner + ')' : c.name;
  }).join(', ');
}

/** 시트의 출석 값 -> [ '84%' | 'A' | '', 메모로 보낼 문자열 ] */
function parseAttendance_(v) {
  if (v === null || v === undefined || v === '') return ['', ''];
  if (typeof v === 'number') return [Math.round(v * 100) + '%', ''];
  var s = s_(v);
  var m = s.match(GRADE_RE_);
  if (m) return [m[1], ''];
  if (s === '-' || s === '#N/A') return ['', ''];
  return ['', s];
}

/** 시트를 가정 블록(행 묶음)으로 나눈다. 모든 구역 열이 같은 행 구조를 공유한다. */
function readBlocks_(rows) {
  var headerIdx = -1;
  for (var i = 0; i < rows.length; i++) {
    if (s_(rows[i][2]) === '1구역') { headerIdx = i; break; }
  }
  if (headerIdx < 0) throw new Error("'1구역' 머리글을 찾지 못했습니다.");
  var header = rows[headerIdx];
  var zoneCols = [];
  for (var c = 2; c < header.length; c++) {
    if (s_(header[c])) zoneCols.push([c, s_(header[c])]);
  }

  var blocks = [];
  var role = '';
  var cur = null;
  for (var r = headerIdx + 1; r < rows.length; r++) {
    var row = rows[r];
    var a = s_(row[0]), label = s_(row[1]);
    var cells = zoneCols.map(function (zc) { return s_(row[zc[0]]); });
    if (a) role = a;
    var loveMarker = label === '사랑구역' || (!label && cells.indexOf('사랑구역') >= 0);
    if (loveMarker) { role = '사랑구역'; cur = null; continue; }
    if (!label && !cells.some(function (x) { return x; })) continue;
    var pos = cur ? cur.rows.length : 0;
    if (!label) label = pos < POSITIONAL_.length ? POSITIONAL_[pos] : '기타';
    if (label === '이름' && (cur === null || pos >= 3)) {
      cur = { role: role, rows: [] };
      blocks.push(cur);
    }
    if (cur === null) continue;
    cur.rows.push([label.replace(/ /g, ''), row, r]);
  }
  return { zoneCols: zoneCols, blocks: blocks };
}

function buildFamily_(role, block, col, backgrounds) {
  var attM = [], attF = [], memo = [], childrenText = '';
  var moveUp = false;
  var bgOf = function (item) { return backgrounds && backgrounds[item[2]] ? backgrounds[item[2]][col] : ''; };
  var nameI = 0, phoneI = 0;
  var raw = ['', '', '', ''];  // 형제 이름, 형제 번호, 자매 이름, 자매 번호
  block.forEach(function (item) {
    var label = item[0], v = item[1][col], s = s_(v);
    if (s && isMoveUpColor_(bgOf(item)) && (label === '자녀' || looksLikeChildren_(s))) moveUp = true;
    if (label === '이름') {
      if (nameI < 2) raw[nameI * 2] = s;
      nameI++;
    } else if (label === '전화번호') {
      if (phoneI < 2) raw[phoneI * 2 + 1] = s;
      phoneI++;
    } else if (label === '자녀') {
      if (s && s !== '0') childrenText = s;
    } else if (label === '남출석' || label === '여출석' || label === '기타') {
      var p = parseAttendance_(v), att = p[0];
      if (label === '남출석' || (label === '기타' && att && !attM.length)) {
        if (att) attM.push(att);
      } else if (att) {
        attF.push(att);
      }
      if (p[1]) memo.push(p[1]);
    } else if (label === '메모' || label === '비고') {
      if (s) memo.push(s);
    }
  });

  // 셀이 한 칸씩 밀려 입력된 경우 바로잡기
  var persons = [], leftoverChildren = [];
  [[raw[0], raw[1]], [raw[2], raw[3]]].forEach(function (pair) {
    var nameV = pair[0], phoneV = pair[1];
    if (looksLikeChildren_(nameV)) { leftoverChildren.push(nameV); nameV = ''; }
    if (looksLikeChildren_(phoneV)) { leftoverChildren.push(phoneV); phoneV = ''; }
    if (isPhone_(nameV) && !phoneV) { phoneV = nameV; nameV = ''; }
    if (!nameV && phoneV && !isPhone_(phoneV) && PERSON_RE_.test(phoneV)) { nameV = phoneV; phoneV = ''; }
    persons.push([nameV, phoneV]);
  });
  // 이름 없이 번호만 있는 사람 -> 앞사람 번호로
  if (!persons[1][0] && persons[1][1] && persons[0][0] && !persons[0][1]) {
    persons[0][1] = persons[1][1]; persons[1][1] = '';
  }
  if (!persons[1][0] && isPhone_(persons[1][1]) && persons[0][0] && !isPhone_(persons[0][1])) {
    persons[0][1] = persons[1][1]; persons[1][1] = '';
  }

  var text = childrenText || leftoverChildren.join(' ');
  if (childrenText && leftoverChildren.length) text = childrenText + ' ' + leftoverChildren.join(' ');

  var out = {
    role: role || '구역원',
    children: parseChildren_(text),
    ref_att_m: attM[0] || '',
    ref_att_f: attF[0] || '',
    sheet_memo: memo.join('\n'),
    move_up: moveUp
  };
  ['husband', 'wife'].forEach(function (key, i) {
    var nameV = persons[i][0], phoneV = persons[i][1];
    var person = parsePerson_(nameV);
    out[key + '_name'] = person[0];
    out[key + '_birth'] = person[1];
    out[key + '_phone'] = (!phoneV || isPhone_(phoneV)) ? phoneV : '';
    if (phoneV && !isPhone_(phoneV)) {
      out.sheet_memo = (out.sheet_memo + '\n연락처 칸: ' + phoneV).trim();
    }
  });
  if (!out.husband_name && !out.wife_name) return null;
  return out;
}

/**
 * 시트 값(getValues 결과)과 배경색(getBackgrounds 결과) -> [{name, leader_names, families: [...]}]
 */
function parseSourceRows_(rows, backgrounds) {
  var parsed = readBlocks_(rows);
  return parsed.zoneCols.map(function (zc) {
    var col = zc[0], zoneLabel = zc[1];
    var families = [], leaders = [];
    parsed.blocks.forEach(function (b) {
      var fam = buildFamily_(b.role, b.rows, col, backgrounds);
      if (!fam) return;
      if (zoneLabel === '임원') fam.role = '임원';
      families.push(fam);
      if (fam.role === '구역장' || (zoneLabel === '임원' && !leaders.length)) {
        leaders = [fam.husband_name, fam.wife_name].filter(function (n) { return n; });
      }
    });
    return { name: zoneLabel, leader_names: leaders.join(' · '), families: families };
  });
}

if (typeof module !== 'undefined') {
  module.exports = { parseSourceRows_: parseSourceRows_, parseChildren_: parseChildren_, formatChildren_: formatChildren_ };
}
