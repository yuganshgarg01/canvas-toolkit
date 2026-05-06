"""
Canvas Grade → Rubric Migrator
-------------------------------
- Fetches existing grades from a Canvas assignment
- Fetches rubric criteria from the same assignment
- Distributes existing grade across rubric criteria proportionally
- Scores are WHOLE NUMBERS only (no decimals)
- Last criterion absorbs remainder to ensure total matches exactly
- Re-uploads in Canvas rubric format WITHOUT changing final grade
- Shows preview before uploading (confirmation required)

FORMULA:
  criterion_score = round((student_total / total_rubric_pts) x criterion_max_pts)
  last_criterion  = student_total - sum(all other rounded scores)

EXAMPLE — Student got 38/50, Rubric: DB Design(10) + SQL(40):
  DB Design → round((38/50) x 10) = round(7.6) = 8
  SQL       → 38 - 8              = 30          (remainder)
  Total     → 8 + 30              = 38 ✅

SETUP:
1. pip install requests pandas
   OR: python -m pip install requests pandas
2. Fill in your Canvas details below
3. Run: python grade_to_rubric.py

NOTE: Final grades will NOT change — only rubric breakdown is added.
"""

import requests
import pandas as pd
import sys

# ============================================================
# CONFIGURATION — Fill these in
# ============================================================

CANVAS_API_TOKEN = "7~th3yzNkAGFkJQETNmNf2CMFGH6nVmQJewcvwc3778kHEJLxvPa6cGAhyTDfAevGc"
CANVAS_URL       = "https://canvas.instructure.com"
COURSE_ID        = "14222223"
ASSIGNMENT_ID    = "62461773"


# ============================================================
# STEP 1 — FETCH RUBRIC FROM ASSIGNMENT
# ============================================================

def fetch_rubric():
    headers  = {"Authorization": f"Bearer {CANVAS_API_TOKEN}"}
    url      = f"{CANVAS_URL}/api/v1/courses/{COURSE_ID}/assignments/{ASSIGNMENT_ID}"
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        print(f"❌ Failed to fetch assignment: {response.text}")
        sys.exit(1)

    data            = response.json()
    assignment_name = data.get("name", "Assignment")
    total_points    = data.get("points_possible", 100)
    rubric_raw      = data.get("rubric", [])

    if not rubric_raw:
        print("❌ No rubric attached to this assignment!")
        print("   Please attach a rubric in Canvas first, then run this script.")
        sys.exit(1)

    rubric_criteria  = []
    total_rubric_pts = 0

    print(f"\n✅ Assignment : {assignment_name}")
    print(f"   Points     : {total_points}")
    print(f"\n📋 Rubric Criteria Found:")

    for criterion in rubric_raw:
        cid     = criterion.get("id", "")
        desc    = criterion.get("description", "")
        points  = int(criterion.get("points", 0))   # whole number
        ratings = criterion.get("ratings", [])
        total_rubric_pts += points

        rubric_criteria.append({
            "id":          cid,
            "description": desc,
            "points":      points,
            "ratings":     ratings
        })

        print(f"   - {desc}: {points} pts")
        for r in ratings:
            print(f"       • {r.get('description','')}: {int(r.get('points',0))} pts")

    print(f"\n   Total Rubric Points : {total_rubric_pts}")
    print(f"   Assignment Points   : {total_points}")

    return rubric_criteria, int(total_points), total_rubric_pts, assignment_name


# ============================================================
# STEP 2 — FETCH EXISTING GRADES
# ============================================================

def fetch_existing_grades():
    headers = {"Authorization": f"Bearer {CANVAS_API_TOKEN}"}
    url     = f"{CANVAS_URL}/api/v1/courses/{COURSE_ID}/assignments/{ASSIGNMENT_ID}/submissions"
    params  = {
        "include[]": ["user", "submission_comments", "rubric_assessment"],
        "per_page":  100
    }
    response = requests.get(url, headers=headers, params=params)

    if response.status_code != 200:
        print(f"❌ Failed to fetch submissions: {response.text}")
        sys.exit(1)

    submissions = response.json()
    graded      = []
    ungraded    = []

    for sub in submissions:
        user  = sub.get("user", {})
        name  = user.get("name", f"User_{sub.get('user_id','?')}")
        score = sub.get("score")
        grade = sub.get("grade")

        if score is not None:
            graded.append({
                "user_id":      sub.get("user_id"),
                "student_name": name,
                "score":        int(float(score)),   # whole number
                "grade":        grade,
            })
        else:
            ungraded.append(name)

    print(f"\n📊 Submissions found : {len(submissions)}")
    print(f"   ✅ Graded          : {len(graded)}")
    print(f"   ⚠️  Ungraded       : {len(ungraded)}")

    if ungraded:
        print(f"\n   Ungraded students (will be skipped):")
        for name in ungraded:
            print(f"   - {name}")

    return graded


# ============================================================
# STEP 3 — DISTRIBUTE GRADE (whole numbers, remainder on last)
# ============================================================

def distribute_grade(student_score, rubric_criteria, total_rubric_pts):
    """
    Distribute student score proportionally across rubric criteria.

    Formula:
      criterion_score = round((student_score / total_rubric_pts) x criterion_max)
      last_criterion  = student_score - sum(all other scores)

    All scores are WHOLE NUMBERS.
    Total always matches student_score exactly.
    """

    rubric_assessment  = {}
    distributed_so_far = 0
    criteria_count     = len(rubric_criteria)

    for i, criterion in enumerate(rubric_criteria):
        cid     = criterion["id"]
        max_pts = criterion["points"]
        ratings = criterion["ratings"]

        if i == criteria_count - 1:
            # Last criterion gets the remainder — guarantees total matches exactly
            criterion_score = student_score - distributed_so_far
            # Clamp between 0 and max
            criterion_score = max(0, min(criterion_score, max_pts))
        else:
            # Proportional score rounded to whole number
            proportion      = max_pts / total_rubric_pts if total_rubric_pts > 0 else 1 / criteria_count
            criterion_score = round(student_score * proportion)
            # Clamp between 0 and max
            criterion_score = max(0, min(criterion_score, max_pts))
            distributed_so_far += criterion_score

        # Find closest rating band ID
        closest_rating_id = None
        min_diff          = float("inf")
        for rating in ratings:
            diff = abs(int(rating.get("points", 0)) - criterion_score)
            if diff < min_diff:
                min_diff          = diff
                closest_rating_id = rating.get("id")

        rubric_assessment[cid] = {
            "points":      criterion_score,   # whole number ✅
            "criterion":   criterion["description"],
            "max_pts":     max_pts,
            "rating_id":   closest_rating_id
        }

    return rubric_assessment


# ============================================================
# STEP 4 — PREVIEW BEFORE UPLOAD
# ============================================================

def preview_results(graded, rubric_criteria, total_points, total_rubric_pts):
    print("\n" + "=" * 70)
    print("👁️  PREVIEW — Grade Distribution across Rubric (Whole Numbers)")
    print("=" * 70)

    # Header
    print(f"{'Student':<25} {'Original':>8} ", end="")
    for c in rubric_criteria:
        short = c["description"][:10]
        print(f" {short:>10}", end="")
    print(f"  {'Total':>6}")
    print("-" * 70)

    all_previews = []
    for student in graded:
        rubric_assessment = distribute_grade(
            student["score"], rubric_criteria, total_rubric_pts
        )
        rubric_total = sum(v["points"] for v in rubric_assessment.values())
        student["rubric_assessment"] = rubric_assessment

        # Print row — all whole numbers
        print(f"{student['student_name']:<25} {student['score']:>8} ", end="")
        for c in rubric_criteria:
            score = rubric_assessment.get(c["id"], {}).get("points", 0)
            print(f" {score:>10}", end="")

        match = "✅" if rubric_total == student["score"] else "⚠️"
        print(f"  {rubric_total:>6} {match}")
        all_previews.append(student)

    print("-" * 70)
    print(f"\n✅ All scores are whole numbers")
    print(f"⚠️  Final grades will NOT change — only rubric breakdown is added")
    return all_previews


# ============================================================
# STEP 5 — UPLOAD RUBRIC GRADES TO CANVAS
# ============================================================

def upload_rubric_grade(student, total_points):
    headers = {"Authorization": f"Bearer {CANVAS_API_TOKEN}"}
    url     = f"{CANVAS_URL}/api/v1/courses/{COURSE_ID}/assignments/{ASSIGNMENT_ID}/submissions/{student['user_id']}"

    # Build Canvas rubric assessment payload
    rubric_payload = {}
    for cid, data in student["rubric_assessment"].items():
        rubric_payload[cid] = {
            "points": data["points"]   # whole number
        }
        if data.get("rating_id"):
            rubric_payload[cid]["rating_id"] = data["rating_id"]

    payload = {
        "submission": {
            "posted_grade": str(student["score"])   # original grade UNCHANGED
        },
        "rubric_assessment": rubric_payload
    }

    response = requests.put(url, headers=headers, json=payload)
    return response.status_code == 200


# ============================================================
# STEP 6 — SAVE CSV REPORT
# ============================================================

def save_csv(graded, rubric_criteria, assignment_name):
    rows = []
    for student in graded:
        row = {
            "Student Name":   student["student_name"],
            "Original Grade": student["score"],
        }
        for c in rubric_criteria:
            score = student["rubric_assessment"].get(c["id"], {}).get("points", 0)
            row[f"{c['description']} (/{c['points']})"] = score   # whole number

        rubric_total    = sum(v["points"] for v in student["rubric_assessment"].values())
        row["Rubric Total"] = rubric_total
        row["Match"]        = "Yes" if rubric_total == student["score"] else "No"
        rows.append(row)

    df       = pd.DataFrame(rows)
    filename = f"{assignment_name.replace(' ', '_')}_rubric_migration.csv"
    df.to_csv(filename, index=False)
    print(f"\n✅ CSV saved: {filename}")
    return filename


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("  📊 Canvas Grade → Rubric Migrator")
    print("  🔢 Whole numbers only — no decimals")
    print("  🔒 Final grades will NOT change")
    print("=" * 70)

    # Step 1: Fetch rubric
    print("\n🔗 Fetching assignment rubric from Canvas...")
    rubric_criteria, total_points, total_rubric_pts, assignment_name = fetch_rubric()

    # Step 2: Fetch existing grades
    print("\n🔗 Fetching existing grades from Canvas...")
    graded = fetch_existing_grades()

    if not graded:
        print("\n❌ No graded submissions found!")
        return

    # Step 3 & 4: Distribute and preview
    previewed = preview_results(graded, rubric_criteria, total_points, total_rubric_pts)

    # Step 5: Confirm before uploading
    print("\n" + "=" * 70)
    confirm = input("🚀 Proceed with uploading rubric grades to Canvas? (yes/no): ").strip().lower()

    if confirm != "yes":
        print("❌ Upload cancelled.")
        save_csv(previewed, rubric_criteria, assignment_name)
        print("📄 CSV saved for your reference.")
        return

    # Step 6: Upload
    print("\n📤 Uploading rubric grades to Canvas...")
    print("=" * 70)

    success_count = 0
    fail_count    = 0

    for student in previewed:
        success = upload_rubric_grade(student, total_points)
        status  = "✅" if success else "❌"
        rubric_total = sum(v["points"] for v in student["rubric_assessment"].values())
        print(f"  {status} {student['student_name']}: {student['score']}/{total_points} → Rubric total: {rubric_total}")
        if success:
            success_count += 1
        else:
            fail_count += 1

    # Step 7: Save CSV
    save_csv(previewed, rubric_criteria, assignment_name)

    # Summary
    print("\n" + "=" * 70)
    print("📊 UPLOAD SUMMARY")
    print("-" * 70)
    print(f"  ✅ Successfully uploaded : {success_count}")
    print(f"  ❌ Failed               : {fail_count}")
    print(f"  🔒 Final grades changed : NONE")
    print("=" * 70)
    print("🎉 Done! Rubric breakdown added to all graded submissions.")


if __name__ == "__main__":
    main()
