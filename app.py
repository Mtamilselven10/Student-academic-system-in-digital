import os
import uuid
from flask import Flask, render_template, request, redirect, url_for, flash, session
from controller.database import db
from controller.config import Config
from controller.models import (
    User, Role, UserRole,
    StudentProfile, StaffProfile,
    Result, Marks, Attendance, AdminProfile
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import text

app = Flask(__name__)
app.config.from_object(Config)
app.config["UPLOAD_FOLDER"] = os.path.join("static", "uploads")

db.init_app(app)

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


def allowed_image_file(filename):
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_IMAGE_EXTENSIONS


def get_current_student(user_id):
    student = StudentProfile.query.filter_by(user_id=user_id).first()
    if not student:
        student = StudentProfile(user_id=user_id)
        db.session.add(student)
        db.session.commit()
    return student


def get_current_staff_profile(user_id):
    staff = StaffProfile.query.filter_by(user_id=user_id).first()
    if not staff:
        staff = StaffProfile(user_id=user_id)
        db.session.add(staff)
        db.session.commit()
    return staff


def is_student_profile_complete(student):
    required_fields = [
        student.register_number,
        student.batch,
        student.course,
        student.branch,
        student.gender,
        student.dob,
        student.personal_email,
        student.mobile,
        student.address,
    ]
    return all(value is not None and str(value).strip() for value in required_fields)


# ---------------- CREATE TABLES ----------------

with app.app_context():
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    db.create_all()
    staff_columns = [row[1] for row in db.session.execute(text("PRAGMA table_info(staff_profile)")).all()]
    if "photo" not in staff_columns:
        db.session.execute(text("ALTER TABLE staff_profile ADD COLUMN photo VARCHAR(200)"))
        db.session.commit()
    admin_role = Role.query.filter_by(name="Admin").first()
    if not admin_role:
        admin_role = Role(name="Admin")
        db.session.add(admin_role)
        db.session.flush()

    admins = [
        {"email": "tamil1@gmail.com", "password": "1234567890"},
        {"email": "praveen@gmail.com", "password": "123456789"},
        {"email": "gopi@gmail.com", "password": "12345678"},
    ]

    for admin in admins:
        existing_user = User.query.filter_by(email=admin["email"]).first()

        if not existing_user:
            new_admin = User(
                username=admin["email"],   # just store email as username
                email=admin["email"],
                password=generate_password_hash(admin["password"])
            )
            db.session.add(new_admin)
            db.session.flush()
            existing_user = new_admin

        existing_admin_role = UserRole.query.filter_by(
            user_id=existing_user.user_id,
            role_id=admin_role.role_id
        ).first()
        if not existing_admin_role:
            db.session.add(UserRole(user_id=existing_user.user_id, role_id=admin_role.role_id))

    db.session.commit()

    # Create default roles if not exists
    default_roles = ["Staff", "Student"]
    for role_name in default_roles:
        if not Role.query.filter_by(name=role_name).first():
            db.session.add(Role(name=role_name))
    db.session.commit()


# ================= HOME =================
@app.route("/")
def index():
    if "role" in session:
        if session["role"] == "Admin":
            return redirect(url_for("admin_dashboard"))
        elif session["role"] == "Staff":
            return redirect(url_for("staff_dashboard"))
        elif session["role"] == "Student":
            student = get_current_student(session.get("user_id"))
            if not is_student_profile_complete(student):
                return redirect(url_for("student_profile", setup=1))
            return redirect(url_for("student_dashboard"))
    return redirect(url_for("login"))


# ================= REGISTER =================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")
        role_name = request.form.get("role")
        allowed_roles = {"Student", "Staff"}

        if role_name not in allowed_roles:
            flash("Admin account can be created only by system")
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(password)

        try:
            new_user = User(username=username, email=email, password=hashed_password)
            db.session.add(new_user)
            db.session.flush()  # Get user_id

            role = Role.query.filter_by(name=role_name).first()

            if not role:
                flash("Role not found")
                db.session.rollback()
                return redirect(url_for("register"))

            user_role = UserRole(user_id=new_user.user_id, role_id=role.role_id)
            db.session.add(user_role)

            # Create profiles based on role
            if role_name == "Student":
                db.session.add(StudentProfile(user_id=new_user.user_id))

            elif role_name == "Staff":
                db.session.add(StaffProfile(user_id=new_user.user_id))

            db.session.commit()
            flash("Registration Successful!")
            return redirect(url_for("login"))

        except Exception as e:
            db.session.rollback()
            flash(str(e))

    return render_template("register.html")


# ================= LOGIN =================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        user = User.query.filter_by(email=email).first()

        if user:
            if check_password_hash(user.password, password):
                session["user_id"] = user.user_id
                session["username"] = user.username

                user_roles = (
                    db.session.query(Role.name)
                    .join(UserRole, UserRole.role_id == Role.role_id)
                    .filter(UserRole.user_id == user.user_id)
                    .all()
                )
                role_names = {row[0] for row in user_roles}

                if "Admin" in role_names:
                    session["role"] = "Admin"
                    return redirect(url_for("index"))
                if "Staff" in role_names:
                    session["role"] = "Staff"
                    return redirect(url_for("index"))
                if "Student" in role_names:
                    session["role"] = "Student"
                    student = StudentProfile.query.filter_by(user_id=user.user_id).first()
                    if not student:
                        student = StudentProfile(user_id=user.user_id)
                        db.session.add(student)
                        db.session.commit()

                    if not is_student_profile_complete(student):
                        return redirect(url_for("student_profile", setup=1))
                    return redirect(url_for("student_dashboard"))

            flash("Invalid password")
            return render_template("login.html", show_forgot=True, forgot_email=email)

        flash("Invalid Credentials")
        return render_template("login.html", show_forgot=False)

    return render_template("login.html", show_forgot=False)


@app.route("/forgot_password", methods=["POST"])
def forgot_password():
    email = (request.form.get("email") or "").strip().lower()
    new_password = request.form.get("new_password") or ""
    confirm_password = request.form.get("confirm_password") or ""

    if not email or not new_password or not confirm_password:
        flash("All forgot password fields are required")
        return render_template("login.html", show_forgot=True, forgot_email=email)

    if new_password != confirm_password:
        flash("New password and confirm password must match")
        return render_template("login.html", show_forgot=True, forgot_email=email)

    if len(new_password) < 6:
        flash("New password must be at least 6 characters")
        return render_template("login.html", show_forgot=True, forgot_email=email)

    user = User.query.filter_by(email=email).first()
    if not user:
        flash("Email not found")
        return render_template("login.html", show_forgot=True, forgot_email=email)

    user.password = generate_password_hash(new_password)
    db.session.commit()
    flash("Password updated successfully. Please login.")
    return redirect(url_for("login"))


# ================= STUDENT DASHBOARD =================
@app.route("/student_dashboard")
def student_dashboard():
    if session.get("role") != "Student":
        return redirect(url_for("login"))

    student = get_current_student(session.get("user_id"))
    profile_complete = is_student_profile_complete(student)
    if not profile_complete:
        flash("Please complete your profile first")
        return redirect(url_for("student_profile", setup=1))

    return render_template(
        "student_dashboard.html",
        student=student,
        profile_complete=profile_complete,
        current_page="dashboard"
    )


# ================= STUDENT PROFILE VIEW =================
@app.route("/student_profile_view")
def student_profile_view():
    if session.get("role") != "Student":
        return redirect(url_for("login"))

    student = get_current_student(session.get("user_id"))
    return render_template(
        "student_profile_view.html",
        student=student,
        profile_complete=is_student_profile_complete(student),
        current_page="profile"
    )


# ================= STUDENT RESULTS =================
@app.route("/student_results")
def student_results():
    if session.get("role") != "Student":
        return redirect(url_for("login"))

    student = get_current_student(session.get("user_id"))
    return render_template(
        "student_results.html",
        student=student,
        results=student.results,
        marks=student.marks,
        attendance=student.attendance,
        profile_complete=is_student_profile_complete(student),
        current_page="results"
    )


# ================= STUDENT ATTACHMENT =================
@app.route("/student_attachment", methods=["GET", "POST"])
def student_attachment():
    if session.get("role") != "Student":
        return redirect(url_for("login"))

    student = get_current_student(session.get("user_id"))
    if request.method == "POST":
        file = request.files.get("photo_file")
        if not file or file.filename == "":
            flash("Please choose a photo file")
            return redirect(url_for("student_attachment"))

        if not allowed_image_file(file.filename):
            flash("Only PNG, JPG, JPEG, GIF, WEBP files are allowed")
            return redirect(url_for("student_attachment"))

        original_name = secure_filename(file.filename)
        ext = original_name.rsplit(".", 1)[1].lower()
        saved_name = f"user_{student.user_id}_{uuid.uuid4().hex[:8]}.{ext}"
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], saved_name)
        file.save(save_path)

        student.photo = os.path.join("uploads", saved_name).replace("\\", "/")
        db.session.commit()
        flash("Attachment uploaded successfully")
        return redirect(url_for("student_attachment"))

    return render_template(
        "student_attachment.html",
        student=student,
        profile_complete=is_student_profile_complete(student),
        current_page="attachment"
    )


# ================= STUDENT PROFILE EDIT =================
@app.route("/student_profile", methods=["GET", "POST"])
def student_profile():
    if session.get("role") != "Student":
        return redirect(url_for("login"))

    student = get_current_student(session.get("user_id"))

    is_setup_mode = request.args.get("setup") == "1" or not is_student_profile_complete(student)

    if request.method == "POST":
        student.register_number = request.form.get("register_number")
        student.batch = request.form.get("batch") 
        student.course = request.form.get("course")
        student.branch = request.form.get("branch")
        student.gender = request.form.get("gender")
        student.dob = request.form.get("dob")
        student.hostel = request.form.get("hostel")
        student.bus = request.form.get("bus")
        student.admission_quota = request.form.get("admission_quota")
        student.first_graduate = request.form.get("first_graduate")
        student.personal_email = request.form.get("personal_email")
        student.college_email = request.form.get("college_email")
        student.mobile = request.form.get("mobile")
        student.address = request.form.get("address")

        db.session.commit()
        if is_setup_mode:
            flash("Profile saved successfully")
        else:
            flash("Student profile updated successfully")
        return redirect(url_for("student_profile_view"))

    return render_template(
        "student.html",
        student=student,
        is_setup_mode=is_setup_mode,
        results=student.results,
        marks=student.marks,
        attendance=student.attendance
    )


# ================= UPDATE RESULT =================
@app.route("/update_result/<int:result_id>", methods=["POST"])
def update_result(result_id):
    if session.get("role") != "Student":
        return redirect(url_for("login"))

    student = get_current_student(session.get("user_id"))
    result = Result.query.filter_by(id=result_id, student_id=student.id).first()
    if not result:
        flash("Result record not found")
        return redirect(url_for("student_profile"))

    result.semester = request.form.get("semester")
    result.subject_code = request.form.get("subject_code")
    result.subject_name = request.form.get("subject_name")
    result.grade = request.form.get("grade")
    result.result_status = request.form.get("result_status")
    result.month_year = request.form.get("month_year")
    db.session.commit()
    flash("Result updated successfully")
    return redirect(url_for("student_profile"))


# ================= UPDATE MARKS =================
@app.route("/update_marks/<int:marks_id>", methods=["POST"])
def update_marks(marks_id):
    if session.get("role") != "Student":
        return redirect(url_for("login"))

    student = get_current_student(session.get("user_id"))
    marks = Marks.query.filter_by(id=marks_id, student_id=student.id).first()
    if not marks:
        flash("Marks record not found")
        return redirect(url_for("student_profile"))

    subject = request.form.get("subject")
    marks_value = request.form.get("marks")
    try:
        marks_value = int(marks_value)
    except (TypeError, ValueError):
        flash("Marks must be a number")
        return redirect(url_for("student_profile"))

    marks.subject = subject
    marks.marks = marks_value
    db.session.commit()
    flash("Marks updated successfully")
    return redirect(url_for("student_profile"))


# ================= UPDATE ATTENDANCE =================
@app.route("/update_attendance/<int:attendance_id>", methods=["POST"])
def update_attendance(attendance_id):
    if session.get("role") != "Student":
        return redirect(url_for("login"))

    student = get_current_student(session.get("user_id"))
    attendance = Attendance.query.filter_by(id=attendance_id, student_id=student.id).first()
    if not attendance:
        flash("Attendance record not found")
        return redirect(url_for("student_profile"))

    subject = request.form.get("subject")
    percentage = request.form.get("attendance_percentage")
    try:
        percentage = float(percentage)
    except (TypeError, ValueError):
        flash("Attendance must be a number")
        return redirect(url_for("student_profile"))

    attendance.subject = subject
    attendance.attendance_percentage = percentage
    db.session.commit()
    flash("Attendance updated successfully")
    return redirect(url_for("student_profile"))


# ================= ADD RESULT =================
@app.route("/add_result", methods=["POST"])
def add_result():
    if session.get("role") != "Student":
        return redirect(url_for("login"))

    student = get_current_student(session.get("user_id"))

    if not student:
        flash("Student profile not found")
        return redirect(url_for("student_results"))

    new_result = Result(
        semester=request.form.get("semester"),
        subject_code=request.form.get("subject_code"),
        subject_name=request.form.get("subject_name"),
        grade=request.form.get("grade"),
        result_status=request.form.get("result_status"),
        month_year=request.form.get("month_year"),
        student_id=student.id
    )

    db.session.add(new_result)
    db.session.commit()

    flash("Result Added Successfully")
    return redirect(url_for("student_results"))


# ================= ADD MARKS =================
@app.route("/add_marks", methods=["POST"])
def add_marks():
    if session.get("role") != "Student":
        return redirect(url_for("login"))

    student = get_current_student(session.get("user_id"))
    if not student:
        flash("Student profile not found")
        return redirect(url_for("student_results"))

    subject = request.form.get("subject")
    marks_value = request.form.get("marks")

    if not subject or marks_value is None:
        flash("Subject and marks are required")
        return redirect(url_for("student_results"))

    try:
        marks_value = int(marks_value)
    except ValueError:
        flash("Marks must be a number")
        return redirect(url_for("student_results"))

    db.session.add(Marks(student_id=student.id, subject=subject, marks=marks_value))
    db.session.commit()
    flash("Marks added successfully")
    return redirect(url_for("student_results"))


# ================= ADD ATTENDANCE =================
@app.route("/add_attendance", methods=["POST"])
def add_attendance():
    if session.get("role") != "Student":
        return redirect(url_for("login"))

    student = get_current_student(session.get("user_id"))
    if not student:
        flash("Student profile not found")
        return redirect(url_for("student_results"))

    subject = request.form.get("subject")
    percentage = request.form.get("attendance_percentage")

    if not subject or percentage is None:
        flash("Subject and attendance are required")
        return redirect(url_for("student_results"))

    try:
        percentage = float(percentage)
    except ValueError:
        flash("Attendance must be a number")
        return redirect(url_for("student_results"))

    db.session.add(Attendance(student_id=student.id, subject=subject, attendance_percentage=percentage))
    db.session.commit()
    flash("Attendance added successfully")
    return redirect(url_for("student_results"))


# ================= STAFF DASHBOARD =================
@app.route("/staff_dashboard")
def staff_dashboard():
    if session.get("role") != "Staff":
        return redirect(url_for("login"))

    register_query = (request.args.get("register_number") or "").strip()
    students_query = StudentProfile.query
    if register_query:
        students_query = students_query.filter(StudentProfile.register_number.ilike(f"%{register_query}%"))
    students = students_query.all()

    current_staff = User.query.get(session.get("user_id"))
    staff_profile = get_current_staff_profile(session.get("user_id"))
    return render_template(
        "staff_dashboard.html",
        students=students,
        staff_email=current_staff.email if current_staff else "-",
        staff_profile=staff_profile,
        register_query=register_query
    )


# ================= STAFF PROFILE PHOTO =================
@app.route("/staff/upload_photo", methods=["POST"])
def staff_upload_photo():
    if session.get("role") != "Staff":
        return redirect(url_for("login"))

    staff_profile = get_current_staff_profile(session.get("user_id"))
    file = request.files.get("photo_file")
    if not file or file.filename == "":
        flash("Please choose a photo")
        return redirect(url_for("staff_dashboard"))

    if not allowed_image_file(file.filename):
        flash("Only PNG, JPG, JPEG, GIF, WEBP files are allowed")
        return redirect(url_for("staff_dashboard"))

    original_name = secure_filename(file.filename)
    ext = original_name.rsplit(".", 1)[1].lower()
    saved_name = f"staff_{staff_profile.user_id}_{uuid.uuid4().hex[:8]}.{ext}"
    save_path = os.path.join(app.config["UPLOAD_FOLDER"], saved_name)
    file.save(save_path)

    staff_profile.photo = os.path.join("uploads", saved_name).replace("\\", "/")
    db.session.commit()
    flash("Staff photo updated")
    return redirect(url_for("staff_dashboard"))


# ================= STAFF REMOVE PHOTO =================
@app.route("/staff/remove_photo", methods=["POST"])
def staff_remove_photo():
    if session.get("role") != "Staff":
        return redirect(url_for("login"))

    staff_profile = get_current_staff_profile(session.get("user_id"))
    staff_profile.photo = None
    db.session.commit()
    flash("Staff photo removed")
    return redirect(url_for("staff_dashboard"))


# ================= STAFF DELETE STUDENT =================
@app.route("/staff/delete_student/<int:student_id>", methods=["POST"])
def staff_delete_student(student_id):
    if session.get("role") != "Staff":
        return redirect(url_for("login"))

    student = StudentProfile.query.get(student_id)
    if not student:
        flash("Student not found")
        return redirect(url_for("staff_dashboard"))

    target_user_id = student.user_id
    db.session.delete(student)

    student_role = Role.query.filter_by(name="Student").first()
    if student_role:
        UserRole.query.filter_by(user_id=target_user_id, role_id=student_role.role_id).delete()

    if UserRole.query.filter_by(user_id=target_user_id).count() == 0:
        user = User.query.get(target_user_id)
        if user:
            db.session.delete(user)

    db.session.commit()
    flash("Student removed successfully")
    return redirect(url_for("staff_dashboard"))


# ================= STAFF STUDENT DETAIL =================
@app.route("/staff/student/<int:student_id>")
def staff_student_detail(student_id):
    if session.get("role") != "Staff":
        return redirect(url_for("login"))

    student = StudentProfile.query.get_or_404(student_id)
    return render_template(
        "staff_student_detail.html",
        student=student,
        results=student.results,
        marks=student.marks,
        attendance=student.attendance
    )


# ================= STAFF ADD RESULT =================
@app.route("/staff/student/<int:student_id>/add_result", methods=["POST"])
def staff_add_result(student_id):
    if session.get("role") != "Staff":
        return redirect(url_for("login"))

    student = StudentProfile.query.get_or_404(student_id)
    db.session.add(Result(
        semester=request.form.get("semester"),
        subject_code=request.form.get("subject_code"),
        subject_name=request.form.get("subject_name"),
        grade=request.form.get("grade"),
        result_status=request.form.get("result_status"),
        month_year=request.form.get("month_year"),
        student_id=student.id
    ))
    db.session.commit()
    flash("Result added by staff")
    return redirect(url_for("staff_student_detail", student_id=student_id))


# ================= STAFF ADD MARKS =================
@app.route("/staff/student/<int:student_id>/add_marks", methods=["POST"])
def staff_add_marks(student_id):
    if session.get("role") != "Staff":
        return redirect(url_for("login"))

    student = StudentProfile.query.get_or_404(student_id)
    try:
        marks_value = int(request.form.get("marks"))
    except (TypeError, ValueError):
        flash("Marks must be a number")
        return redirect(url_for("staff_student_detail", student_id=student_id))

    db.session.add(Marks(
        student_id=student.id,
        subject=request.form.get("subject"),
        marks=marks_value
    ))
    db.session.commit()
    flash("Marks added by staff")
    return redirect(url_for("staff_student_detail", student_id=student_id))


# ================= STAFF ADD ATTENDANCE =================
@app.route("/staff/student/<int:student_id>/add_attendance", methods=["POST"])
def staff_add_attendance(student_id):
    if session.get("role") != "Staff":
        return redirect(url_for("login"))

    student = StudentProfile.query.get_or_404(student_id)
    try:
        percentage = float(request.form.get("attendance_percentage"))
    except (TypeError, ValueError):
        flash("Attendance must be a number")
        return redirect(url_for("staff_student_detail", student_id=student_id))

    db.session.add(Attendance(
        student_id=student.id,
        subject=request.form.get("subject"),
        attendance_percentage=percentage
    ))
    db.session.commit()
    flash("Attendance added by staff")
    return redirect(url_for("staff_student_detail", student_id=student_id))


# ================= ADMIN DASHBOARD =================
@app.route("/admin_dashboard")
def admin_dashboard():
    if session.get("role") != "Admin":
        return redirect(url_for("login"))

    admin_user = User.query.get(session.get("user_id"))
    total_students = StudentProfile.query.count()
    total_staff = StaffProfile.query.count()
    total_users = User.query.count()
    total_results = Result.query.count()
    total_marks = Marks.query.count()
    total_attendance = Attendance.query.count()
    recent_users = User.query.order_by(User.user_id.desc()).limit(8).all()
    admin_members = (
        db.session.query(User)
        .join(UserRole, UserRole.user_id == User.user_id)
        .join(Role, Role.role_id == UserRole.role_id)
        .filter(Role.name == "Admin")
        .order_by(User.user_id.desc())
        .all()
    )

    return render_template(
        "admin.html",
        total_students=total_students,
        total_staff=total_staff,
        total_users=total_users,
        total_results=total_results,
        total_marks=total_marks,
        total_attendance=total_attendance,
        recent_users=recent_users,
        admin_email=admin_user.email if admin_user else "-",
        admin_members=admin_members
    )


# ================= ADMIN ADD ADMIN MEMBER =================
@app.route("/admin/add_admin", methods=["POST"])
def admin_add_member():
    if session.get("role") != "Admin":
        return redirect(url_for("login"))

    username = (request.form.get("username") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    if not username or not email or not password:
        flash("Username, email, and password are required")
        return redirect(url_for("admin_dashboard"))

    if len(password) < 6:
        flash("Password must be at least 6 characters")
        return redirect(url_for("admin_dashboard"))

    if User.query.filter_by(email=email).first():
        flash("Email already exists")
        return redirect(url_for("admin_dashboard"))

    admin_role = Role.query.filter_by(name="Admin").first()
    if not admin_role:
        flash("Admin role not found")
        return redirect(url_for("admin_dashboard"))

    try:
        new_user = User(
            username=username,
            email=email,
            password=generate_password_hash(password)
        )
        db.session.add(new_user)
        db.session.flush()
        db.session.add(UserRole(user_id=new_user.user_id, role_id=admin_role.role_id))
        db.session.commit()
        flash("New admin member added successfully")
    except Exception:
        db.session.rollback()
        flash("Unable to add admin member")

    return redirect(url_for("admin_dashboard"))


# ================= ADMIN REMOVE ADMIN MEMBER =================
@app.route("/admin/remove_admin/<int:user_id>", methods=["POST"])
def admin_remove_member(user_id):
    if session.get("role") != "Admin":
        return redirect(url_for("login"))

    if user_id == session.get("user_id"):
        flash("You cannot remove your current admin account")
        return redirect(url_for("admin_dashboard"))

    target_admin = User.query.get(user_id)
    if not target_admin:
        flash("Admin user not found")
        return redirect(url_for("admin_dashboard"))

    admin_role = Role.query.filter_by(name="Admin").first()
    if not admin_role:
        flash("Admin role not found")
        return redirect(url_for("admin_dashboard"))

    has_admin_role = UserRole.query.filter_by(user_id=target_admin.user_id, role_id=admin_role.role_id).first()
    if not has_admin_role:
        flash("Selected user is not an admin")
        return redirect(url_for("admin_dashboard"))

    password = request.form.get("password") or ""
    if not password:
        flash("Password is required to remove admin")
        return redirect(url_for("admin_dashboard"))

    if not check_password_hash(target_admin.password, password):
        flash("Invalid password for selected admin email")
        return redirect(url_for("admin_dashboard"))

    try:
        admin_profile = AdminProfile.query.filter_by(user_id=target_admin.user_id).first()
        if admin_profile:
            db.session.delete(admin_profile)

        # Remove only Admin role mapping. Keep user account and other roles intact.
        UserRole.query.filter_by(user_id=target_admin.user_id, role_id=admin_role.role_id).delete()
        db.session.commit()
        flash("Admin role removed successfully")
    except Exception:
        db.session.rollback()
        flash("Unable to remove admin role")

    return redirect(url_for("admin_dashboard"))


# ================= ADMIN VIEW STUDENTS =================
@app.route("/admin/students")
def admin_students():
    if session.get("role") != "Admin":
        return redirect(url_for("login"))

    register_query = (request.args.get("register_number") or "").strip()
    students_query = StudentProfile.query
    if register_query:
        students_query = students_query.filter(StudentProfile.register_number.ilike(f"%{register_query}%"))
    students = students_query.order_by(StudentProfile.id.desc()).all()
    return render_template("admin_students.html", students=students, register_query=register_query)


# ================= ADMIN VIEW STAFF =================
@app.route("/admin/staff")
def admin_staff():
    if session.get("role") != "Admin":
        return redirect(url_for("login"))

    email_query = (request.args.get("email") or "").strip()
    staff_query = db.session.query(StaffProfile).join(User, User.user_id == StaffProfile.user_id)
    if email_query:
        staff_query = staff_query.filter(User.email.ilike(f"%{email_query}%"))
    staff_members = staff_query.order_by(StaffProfile.id.desc()).all()
    return render_template("admin_staff.html", staff_members=staff_members, email_query=email_query)


# ================= DELETE USER =================
@app.route("/admin/delete_user/<int:user_id>", methods=["POST"])
def delete_user(user_id):
    if session.get("role") != "Admin":
        return redirect(url_for("login"))

    if user_id == session.get("user_id"):
        flash("You cannot delete your current admin account")
        return redirect(url_for("admin_dashboard"))

    user = User.query.get(user_id)
    if not user:
        flash("User not found")
        return redirect(url_for("admin_dashboard"))

    try:
        # Delete dependent profile data first to avoid FK errors.
        student = StudentProfile.query.filter_by(user_id=user.user_id).first()
        if student:
            db.session.delete(student)

        staff = StaffProfile.query.filter_by(user_id=user.user_id).first()
        if staff:
            db.session.delete(staff)

        admin_profile = AdminProfile.query.filter_by(user_id=user.user_id).first()
        if admin_profile:
            db.session.delete(admin_profile)

        UserRole.query.filter_by(user_id=user.user_id).delete()

        db.session.delete(user)
        db.session.commit()
        flash("User deleted successfully")
    except Exception:
        db.session.rollback()
        flash("Unable to delete user due to linked records")

    return redirect(url_for("admin_dashboard"))


# ================= LOGOUT =================
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ================= RUN =================
if __name__ == "__main__":
    app.run(debug=True, port=5001)


