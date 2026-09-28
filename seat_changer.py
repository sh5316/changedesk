"""
자리 바꾸기 프로그램

고려 사항
  1. 성적: 짝꿍끼리 성적 합이 반 평균에 가깝도록 (상위권-하위권이 짝이 되도록) 배치
  2. 짝꿍 중복: 예전에 짝이었던 학생끼리는 최대한 다시 짝이 되지 않도록 배치
  3. 성별: GENDER_MODE 설정에 따라 남녀 짝 / 같은 성별 짝 / 고려 안 함
  4. 자리: 지난번에 앉았던 책상에는 연속해서 앉지 않도록 배치
  5. 인원: 최대 20명 (홀수면 한 명은 혼자 앉고, 혼자 앉았던 학생은 다음에 우선 제외)

사용법
  python seat_changer.py            # 새 자리 배치 후 저장 여부 확인
  python seat_changer.py --history  # 지금까지의 짝꿍 기록 보기
  python seat_changer.py --reset    # 기록 초기화
  python web.py                     # 웹 화면으로 실행 (http://localhost:8000)
"""

import argparse
import csv
import json
import random
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
STUDENTS_FILE = BASE_DIR / "students.csv"
HISTORY_FILE = BASE_DIR / "history.json"

MAX_STUDENTS = 20
DESKS_PER_ROW = 2  # 한 줄에 놓이는 2인용 책상 수

# 성별 배치 방식
#   "mixed": 남녀가 짝이 되도록
#   "same" : 같은 성별끼리 짝이 되도록
#   None   : 성별은 고려하지 않음
GENDER_MODE = "mixed"
GENDER_MODES = {"mixed": "남녀 짝", "same": "같은 성별 짝", None: "고려 안 함"}

# 점수(비용) 가중치: 값이 클수록 더 강하게 피함
PAST_PAIR_PENALTY = 1000  # 예전 짝과 다시 짝이 되는 경우 (1회당)
SOLO_REPEAT_PENALTY = 500  # 혼자 앉았던 학생이 또 혼자 앉는 경우
GENDER_PENALTY = 300  # GENDER_MODE에 맞지 않는 짝
GRADE_WEIGHT = 1  # 짝의 성적 합이 평균에서 벗어난 정도

SEARCH_TRIES = 300  # 랜덤 시작 횟수 (많을수록 더 좋은 배치를 찾을 확률 증가)

GENDER_ALIASES = {"남": "남", "남자": "남", "m": "남", "male": "남",
                  "여": "여", "여자": "여", "f": "여", "female": "여"}


class StudentError(ValueError):
    """학생 명단이 잘못되었을 때 발생. 메시지는 그대로 사용자에게 보여준다."""


def parse_students(rows, check_count=True):
    """[{"name", "gender", "score"}, ...]를 {이름: {"score": 성적, "gender": "남"/"여"/None}}로 바꾼다."""
    students = {}
    for row in rows:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        if name in students:
            raise StudentError(f"이름이 중복되었습니다: {name}")

        raw_gender = str(row.get("gender") or "").strip().lower()
        if raw_gender and raw_gender not in GENDER_ALIASES:
            raise StudentError(f"{name}의 성별을 알 수 없습니다: {row['gender']} (남/여로 입력해주세요)")

        try:
            score = float(row.get("score"))
        except (TypeError, ValueError):
            raise StudentError(f"{name}의 성적이 숫자가 아닙니다: {row.get('score')}")

        students[name] = {"score": score, "gender": GENDER_ALIASES.get(raw_gender)}

    if check_count:
        if len(students) < 2:
            raise StudentError("학생이 2명 이상이어야 합니다.")
        if len(students) > MAX_STUDENTS:
            raise StudentError(f"학생은 최대 {MAX_STUDENTS}명까지 가능합니다. (현재 {len(students)}명)")
    return students


def load_students(path=STUDENTS_FILE, check_count=True):
    """students.csv(이름,성별,성적)를 읽는다. 성별 열은 없어도 된다."""
    if not path.exists():
        raise StudentError(f"학생 명단 파일이 없습니다: {path}")
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = [{"name": r.get("이름"), "gender": r.get("성별"), "score": r.get("성적")}
                for r in csv.DictReader(f)]
    return parse_students(rows, check_count)


def save_students(students, path=STUDENTS_FILE):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["이름", "성별", "성적"])
        for name, s in students.items():
            writer.writerow([name, s["gender"] or "", f"{s['score']:g}"])


def load_history():
    if not HISTORY_FILE.exists():
        return []
    with open(HISTORY_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def make_record(desks):
    """책상 배치(desks[i] = i+1번 책상의 학생 목록)를 기록 한 건으로 만든다."""
    return {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "pairs": [g for g in desks if len(g) == 2],
        "solo": next((g[0] for g in desks if len(g) == 1), None),
        "seats": {name: d for d, g in enumerate(desks, 1) for name in g},
    }


def pair_key(a, b):
    return tuple(sorted((a, b)))


def count_past(history):
    """예전 짝꿍 횟수와 혼자 앉은 횟수를 센다."""
    pair_count = {}
    solo_count = {}
    for record in history:
        for pair in record["pairs"]:
            key = pair_key(*pair)
            pair_count[key] = pair_count.get(key, 0) + 1
        if record.get("solo"):
            solo_count[record["solo"]] = solo_count.get(record["solo"], 0) + 1
    return pair_count, solo_count


def last_desks(history):
    """바로 지난번에 각 학생이 앉았던 책상 번호. {이름: 책상번호}"""
    if not history:
        return {}
    return history[-1].get("seats", {})


def is_gender_mismatch(g1, g2, mode):
    if mode is None or g1 is None or g2 is None:
        return False
    if mode == "mixed":
        return g1 == g2
    return g1 != g2


class Arranger:
    def __init__(self, students, history, gender_mode=GENDER_MODE):
        if gender_mode not in GENDER_MODES:
            raise ValueError(f"알 수 없는 성별 배치 방식: {gender_mode}")
        self.students = students
        self.gender_mode = gender_mode
        self.pair_count, self.solo_count = count_past(history)
        self.last_desk = last_desks(history)
        scores = [s["score"] for s in students.values()]
        self.target_sum = 2 * sum(scores) / len(scores)

    def gender_mismatch(self, a, b):
        return is_gender_mismatch(self.students[a]["gender"], self.students[b]["gender"], self.gender_mode)

    def pair_cost(self, a, b):
        cost = PAST_PAIR_PENALTY * self.pair_count.get(pair_key(a, b), 0)
        if self.gender_mismatch(a, b):
            cost += GENDER_PENALTY
        cost += GRADE_WEIGHT * abs(self.students[a]["score"] + self.students[b]["score"] - self.target_sum)
        return cost

    def total_cost(self, order):
        """order를 앞에서부터 두 명씩 짝지음. 홀수면 마지막 한 명은 혼자."""
        cost = sum(self.pair_cost(order[i], order[i + 1]) for i in range(0, len(order) - 1, 2))
        if len(order) % 2 == 1:
            cost += SOLO_REPEAT_PENALTY * self.solo_count.get(order[-1], 0)
        return cost

    def improve(self, order):
        """두 학생의 자리를 맞바꿔 비용이 줄면 반영하는 과정을 더 이상 개선이 없을 때까지 반복."""
        best = self.total_cost(order)
        improved = True
        while improved:
            improved = False
            for i in range(len(order)):
                for j in range(i + 1, len(order)):
                    if i // 2 == j // 2:  # 같은 짝끼리 바꾸는 건 의미 없음
                        continue
                    order[i], order[j] = order[j], order[i]
                    cost = self.total_cost(order)
                    if cost < best - 1e-9:
                        best = cost
                        improved = True
                    else:
                        order[i], order[j] = order[j], order[i]
        return order, best

    def desk_conflicts(self, group, desk):
        """이 책상에 앉으면 지난번과 같은 책상에 연속으로 앉게 되는 학생 수."""
        return sum(1 for name in group if self.last_desk.get(name) == desk)

    def assign_desks(self, groups, max_conflicts=0):
        """각 짝(또는 혼자)을 책상에 배정한다. 연속으로 같은 책상에 앉는 학생 수가
        max_conflicts 이하인 배정을 무작위로 찾고, 없으면 None."""
        desk_numbers = list(range(1, len(groups) + 1))
        random.shuffle(desk_numbers)
        assignment = {}

        def backtrack(idx, used, conflicts):
            if idx == len(groups):
                return True
            for desk in desk_numbers:
                if desk in used:
                    continue
                c = conflicts + self.desk_conflicts(groups[idx], desk)
                if c > max_conflicts:
                    continue
                used.add(desk)
                assignment[desk] = groups[idx]
                if backtrack(idx + 1, used, c):
                    return True
                used.discard(desk)
                del assignment[desk]
            return False

        if backtrack(0, set(), 0):
            return [assignment[d] for d in range(1, len(groups) + 1)]
        return None

    def arrange(self, tries=SEARCH_TRIES):
        """비용이 낮은 짝 조합부터 차례로, 지난번과 같은 책상에 앉는 학생이 없게 책상 배정이 되는지 확인한다."""
        names = list(self.students)
        candidates = {}
        for _ in range(tries):
            order = names[:]
            random.shuffle(order)
            order, cost = self.improve(order)
            groups = [order[i:i + 2] for i in range(0, len(order), 2)]
            key = frozenset(frozenset(g) for g in groups)
            candidates.setdefault(key, (cost, groups))

        ranked = [groups for _, groups in sorted(candidates.values(), key=lambda c: c[0])]

        # 연속으로 같은 책상에 앉는 학생 수를 0명부터 허용하며 찾는다 (보통 0명에서 찾아짐)
        for max_conflicts in range(len(names) + 1):
            for groups in ranked:
                groups = [random.sample(g, len(g)) for g in groups]  # 책상 안 왼쪽/오른쪽은 무작위
                desks = self.assign_desks(groups, max_conflicts)
                if desks is not None:
                    return desks

    def report(self, desks):
        """배치 결과가 각 조건을 얼마나 지켰는지 정리한다."""
        pairs = [g for g in desks if len(g) == 2]
        sums = [self.students[a]["score"] + self.students[b]["score"] for a, b in pairs]
        return {
            "repeats": [{"pair": [a, b], "count": self.pair_count[pair_key(a, b)]}
                        for a, b in pairs if self.pair_count.get(pair_key(a, b))],
            "same_desk": [n for d, g in enumerate(desks, 1) for n in g if self.last_desk.get(n) == d],
            "has_last_desk": bool(self.last_desk),
            "gender_rule": GENDER_MODES[self.gender_mode] if self.gender_mode else None,
            "gender_mismatches": [[a, b] for a, b in pairs if self.gender_mismatch(a, b)],
            "has_gender": any(s["gender"] for s in self.students.values()),
            "score_min": min(sums),
            "score_max": max(sums),
        }


def print_chart(desks, students, report):
    def label(name):
        s = students[name]
        gender = f"{s['gender']}," if s["gender"] else ""
        return f"{name}({gender}{s['score']:g})"

    cells = [" · ".join(label(n) for n in g) + ("" if len(g) == 2 else " · (빈자리)") for g in desks]

    width = max(len(c) for c in cells) + 6
    print("\n" + "[ 칠 판 ]".center(width * DESKS_PER_ROW))
    print()
    for i in range(0, len(cells), DESKS_PER_ROW):
        row = cells[i:i + DESKS_PER_ROW]
        print("".join(f"{i + k + 1:>2}. {c}".ljust(width) for k, c in enumerate(row)))
    print()

    if report["repeats"]:
        print("※ 가능한 조합이 부족해 예전 짝과 다시 짝이 된 경우:")
        for r in report["repeats"]:
            print(f"   - {r['pair'][0]} & {r['pair'][1]} ({r['count']}회 짝이었음)")
    else:
        print("✔ 예전 짝과 겹치는 학생이 없습니다.")

    if report["same_desk"]:
        print(f"※ 배치가 불가능해 지난번과 같은 책상에 앉은 학생: {', '.join(report['same_desk'])}")
    elif report["has_last_desk"]:
        print("✔ 지난번과 같은 책상에 앉은 학생이 없습니다.")

    rule = report["gender_rule"]
    if rule:
        if report["gender_mismatches"]:
            names = ", ".join(f"{a} & {b}" for a, b in report["gender_mismatches"])
            print(f"※ 인원 구성상 {rule}이 안 된 경우: {names}")
        elif report["has_gender"]:
            print(f"✔ 모두 {rule}입니다.")

    lo, hi = report["score_min"], report["score_max"]
    print(f"✔ 짝꿍 성적 합: 최저 {lo:g} / 최고 {hi:g} (차이 {hi - lo:g})")


def show_history(history):
    if not history:
        print("저장된 기록이 없습니다.")
        return
    for n, record in enumerate(history, 1):
        print(f"\n[{n}회차] {record['date']}")
        seats = record.get("seats", {})
        for a, b in record["pairs"]:
            desk = f"{seats[a]}번 책상: " if a in seats else ""
            print(f"  {desk}{a} & {b}")
        if record.get("solo"):
            solo = record["solo"]
            desk = f"{seats[solo]}번 책상: " if solo in seats else ""
            print(f"  {desk}{solo} (혼자)")


def main():
    parser = argparse.ArgumentParser(description="자리 바꾸기 프로그램")
    parser.add_argument("--history", action="store_true", help="짝꿍 기록 보기")
    parser.add_argument("--reset", action="store_true", help="짝꿍 기록 초기화")
    parser.add_argument("--yes", "-y", action="store_true", help="묻지 않고 바로 저장")
    args = parser.parse_args()

    history = load_history()

    if args.history:
        show_history(history)
        return
    if args.reset:
        if HISTORY_FILE.exists():
            HISTORY_FILE.unlink()
        print("기록을 초기화했습니다.")
        return

    try:
        students = load_students()
    except StudentError as e:
        raise SystemExit(str(e))
    arranger = Arranger(students, history)
    desks = arranger.arrange()
    print(f"학생 {len(students)}명 / 지난 기록 {len(history)}회")
    print_chart(desks, students, arranger.report(desks))

    if args.yes or input("\n이 자리로 확정하고 기록에 저장할까요? (y/n): ").strip().lower() == "y":
        history.append(make_record(desks))
        save_history(history)
        print("저장했습니다. 다음 자리 바꾸기 때 이번 짝꿍과 이번 책상은 피해서 배치됩니다.")
    else:
        print("저장하지 않았습니다. 다시 실행하면 새로운 배치가 나옵니다.")


if __name__ == "__main__":
    main()
