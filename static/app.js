// ========================================================
// حالة التطبيق العامة (Application State)
// ========================================================
let allStudents = [];
let allBehaviors = [];
let allTeachers = [];
let allReferrals = [];
let selectedStudent = null;
let selectedBehavior = null;
let selectedGradeFilter = 'all';
let currentStatusFilter = 'pending';
let isAudioEnabled = true;
let socket = null;

// ========================================================
// الصوت والتنبيهات الصوتية (Web Audio API Synthesizer)
// ========================================================
function playNotificationSound() {
    if (!isAudioEnabled) return;
    try {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        
        // النغمة الأولى (E5)
        const osc1 = audioCtx.createOscillator();
        const gain1 = audioCtx.createGain();
        osc1.type = 'sine';
        osc1.frequency.setValueAtTime(659.25, audioCtx.currentTime);
        gain1.gain.setValueAtTime(0.3, audioCtx.currentTime);
        gain1.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.4);
        osc1.connect(gain1);
        gain1.connect(audioCtx.destination);
        osc1.start();
        osc1.stop(audioCtx.currentTime + 0.4);

        // النغمة الثانية (B5) نغمة مبهجة بعد 150 ملي ثانية
        setTimeout(() => {
            const osc2 = audioCtx.createOscillator();
            const gain2 = audioCtx.createGain();
            osc2.type = 'sine';
            osc2.frequency.setValueAtTime(987.77, audioCtx.currentTime);
            gain2.gain.setValueAtTime(0.3, audioCtx.currentTime);
            gain2.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.6);
            osc2.connect(gain2);
            gain2.connect(audioCtx.destination);
            osc2.start();
            osc2.stop(audioCtx.currentTime + 0.6);
        }, 150);
    } catch (e) {
        console.warn('Audio play error:', e);
    }
}

function toggleAudio() {
    isAudioEnabled = !isAudioEnabled;
    const icon = document.getElementById('audioIcon');
    const label = document.getElementById('audioLabel');
    if (isAudioEnabled) {
        icon.textContent = '🔔';
        label.textContent = 'الصوت مفعّل';
        showToast('تم تفعيل التنبيهات الصوتية', 'info');
    } else {
        icon.textContent = '🔕';
        label.textContent = 'الصوت مكتوم';
        showToast('تم كتم التنبيهات الصوتية', 'info');
    }
}

// ========================================================
// التنبيهات المنبثقة (Toast Notifications)
// ========================================================
function showToast(message, type = 'info', title = '') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `pointer-events-auto p-4 rounded-2xl shadow-xl border flex items-start gap-3 transition-all duration-300 transform translate-y-2 opacity-0 text-right`;

    let bgColor = 'bg-white text-slate-800 border-slate-200';
    let icon = 'ℹ️';

    if (type === 'urgent' || type === 'new-referral') {
        bgColor = 'bg-rose-900 text-white border-rose-700 shadow-rose-900/40 ring-4 ring-rose-500/20';
        icon = '🚨';
    } else if (type === 'success') {
        bgColor = 'bg-emerald-900 text-white border-emerald-700 shadow-emerald-900/30';
        icon = '✅';
    } else if (type === 'warning') {
        bgColor = 'bg-amber-900 text-white border-amber-700';
        icon = '⚠️';
    }

    toast.className += ` ${bgColor}`;
    toast.innerHTML = `
        <span class="text-2xl">${icon}</span>
        <div class="flex-1">
            ${title ? `<div class="font-bold text-sm mb-0.5">${title}</div>` : ''}
            <div class="text-xs leading-relaxed opacity-95">${message}</div>
        </div>
        <button onclick="this.parentElement.remove()" class="text-white/60 hover:text-white text-sm">✕</button>
    `;

    container.appendChild(toast);

    // ظهور سلس
    requestAnimationFrame(() => {
        toast.classList.remove('translate-y-2', 'opacity-0');
    });

    // إخفاء تلقائي بعد 6 ثوانٍ
    setTimeout(() => {
        toast.classList.add('opacity-0', 'translate-y-2');
        setTimeout(() => toast.remove(), 300);
    }, 6000);
}

// ========================================================
// اتصال WebSocket للإشعارات اللحظية
// ========================================================
function initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        const badge = document.getElementById('wsStatusBadge');
        const text = document.getElementById('wsStatusText');
        if (badge) badge.classList.replace('bg-rose-950/60', 'bg-emerald-950/60');
        if (text) text.textContent = 'متصل لحظياً بالخادم';
    };

    socket.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleIncomingEvent(data);
        } catch (e) {
            console.error('WS Parse Error:', e);
        }
    };

    socket.onclose = () => {
        const badge = document.getElementById('wsStatusBadge');
        const text = document.getElementById('wsStatusText');
        if (badge) badge.classList.replace('bg-emerald-950/60', 'bg-rose-950/60');
        if (text) text.textContent = 'انقطع الاتصال، جاري إعادة المحاولة...';
        setTimeout(initWebSocket, 3000);
    };

    socket.onerror = () => {
        socket.close();
    };
}

function handleIncomingEvent(event) {
    if (event.type === 'NEW_REFERRAL') {
        const ref = event.data;
        playNotificationSound();
        showToast(
            `أحال المعلم: ${ref.teacher_name}<br>الطالب: <strong>${ref.student_name}</strong> (${ref.grade} - ${ref.classroom})<br>السبب: <span class="underline">${ref.behavior_name}</span>`,
            'new-referral',
            '🔔 إحالة سلوكية جديدة وصلت للوكيل!'
        );

        // تحديث البيانات والقائمة تلقائياً
        allReferrals.unshift(ref);
        updateCounters();
        renderReferralCards();
        loadStats();
    } else if (event.type === 'REFERRAL_UPDATED') {
        const updated = event.data;
        const idx = allReferrals.findIndex(r => r.id === updated.id);
        if (idx !== -1) {
            allReferrals[idx] = updated;
            updateCounters();
            renderReferralCards();
        }
        showToast(`تم تحديث الإجراء للإحالة الخاصة بالطالب: ${updated.student_name}`, 'success');
    }
}

// ========================================================
// التبديل بين الواجهات (Tabs Switching)
// ========================================================
function switchTab(tabName) {
    // إخفاء كل الأقسام
    document.querySelectorAll('main > section').forEach(sec => sec.classList.add('hidden'));

    // إزالة تفعيل كل الأزرار
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('bg-white', 'text-emerald-900', 'shadow');
        btn.classList.add('text-emerald-100');
    });

    // تفعيل القسم والزر المختار
    const targetSection = document.getElementById(`section-${tabName}`);
    const targetBtn = document.getElementById(`tab-${tabName}`);

    if (targetSection) targetSection.classList.remove('hidden');
    if (targetBtn) {
        targetBtn.classList.add('bg-white', 'text-emerald-900', 'shadow');
        targetBtn.classList.remove('text-emerald-100');
    }

    if (tabName === 'vice-principal') {
        loadReferrals();
    } else if (tabName === 'students') {
        renderStudentsDirectory();
    } else if (tabName === 'stats') {
        loadStats();
    }
}

// ========================================================
// تحميل البيانات الأولية من الـ API
// ========================================================
async function loadInitialData() {
    try {
        await Promise.all([
            loadTeachers(),
            loadStudents(),
            loadBehaviors(),
            loadReferrals(),
            loadStats()
        ]);
    } catch (e) {
        console.error('Initialization error:', e);
    }
}

async function loadTeachers() {
    const res = await fetch('/api/teachers');
    allTeachers = await res.json();
    const select = document.getElementById('teacherSelect');
    select.innerHTML = '<option value="">-- اختر اسمك من القائمة --</option>';
    allTeachers.forEach(t => {
        const opt = document.createElement('option');
        opt.value = t.name;
        opt.textContent = `${t.name} (${t.subject || 'عام'})`;
        select.appendChild(opt);
    });
}

async function loadStudents() {
    const res = await fetch('/api/students');
    allStudents = await res.json();
    document.getElementById('studentsCountLabel').textContent = `${allStudents.length} طالب مسجل`;
    renderStudentsList();
    renderStudentsDirectory();
}

async function loadBehaviors() {
    const res = await fetch('/api/behaviors');
    allBehaviors = await res.json();
    renderBehaviorsList();
}

async function loadReferrals() {
    const res = await fetch('/api/referrals');
    allReferrals = await res.json();
    updateCounters();
    renderReferralCards();
}

async function loadStats() {
    try {
        const res = await fetch('/api/stats');
        const data = await res.json();

        // قائمة المؤشرات العامة
        const generalList = document.getElementById('statsGeneralList');
        generalList.innerHTML = `
            <div class="flex items-center justify-between p-3 rounded-xl bg-slate-50 border border-slate-100">
                <span class="text-xs font-semibold text-slate-600">إجمالي طلاب المدرسة</span>
                <span class="text-sm font-bold text-slate-900">${data.total_students} طالب</span>
            </div>
            <div class="flex items-center justify-between p-3 rounded-xl bg-slate-50 border border-slate-100">
                <span class="text-xs font-semibold text-slate-600">إجمالي الإحالات المسجلة</span>
                <span class="text-sm font-bold text-indigo-700">${data.total_referrals} إحالة</span>
            </div>
            <div class="flex items-center justify-between p-3 rounded-xl bg-rose-50 border border-rose-100 text-rose-800">
                <span class="text-xs font-semibold">إحالات بانتظار الإجراء</span>
                <span class="text-sm font-bold">${data.pending_referrals}</span>
            </div>
            <div class="flex items-center justify-between p-3 rounded-xl bg-emerald-50 border border-emerald-100 text-emerald-800">
                <span class="text-xs font-semibold">إحالات تم معالجتها وإنهاؤها</span>
                <span class="text-sm font-bold">${data.resolved_referrals}</span>
            </div>
        `;

        // أكثر السلوكيات تسجيلاً
        const topList = document.getElementById('topBehaviorsList');
        if (data.top_behaviors && data.top_behaviors.length > 0) {
            topList.innerHTML = data.top_behaviors.map((b, i) => `
                <div class="p-3 rounded-xl bg-slate-50 border border-slate-100 flex items-center justify-between">
                    <div class="flex items-center gap-2">
                        <span class="w-6 h-6 rounded-full bg-slate-200 text-slate-700 text-xs flex items-center justify-center font-bold">${i + 1}</span>
                        <span class="text-xs font-semibold text-slate-700">${b.behavior_name}</span>
                    </div>
                    <span class="px-2 py-0.5 rounded-lg bg-indigo-100 text-indigo-800 text-xs font-bold">${b.count} مرات</span>
                </div>
            `).join('');
        } else {
            topList.innerHTML = '<div class="text-xs text-slate-400 text-center py-4">لا توجد مخالفات مسجلة بعد.</div>';
        }
    } catch (e) {
        console.error('Stats error:', e);
    }
}

// ========================================================
// تحديث العدادات والإحصائيات للوكيل
// ========================================================
function updateCounters() {
    const pending = allReferrals.filter(r => r.status === 'pending').length;
    const inProgress = allReferrals.filter(r => r.status === 'in_progress').length;
    const resolved = allReferrals.filter(r => r.status === 'resolved').length;
    const total = allReferrals.length;

    document.getElementById('statPendingCount').textContent = pending;
    document.getElementById('statInProgressCount').textContent = inProgress;
    document.getElementById('statResolvedCount').textContent = resolved;
    document.getElementById('statTotalCount').textContent = total;

    // شارة التنبيه في الشريط العلوي
    const badge = document.getElementById('pendingBadge');
    if (pending > 0) {
        badge.textContent = pending;
        badge.classList.remove('hidden');
    } else {
        badge.classList.add('hidden');
    }
}

// ========================================================
// واجهة المعلم: عرض وفلترة الطلاب
// ========================================================
function filterByClass(grade) {
    selectedGradeFilter = grade;
    document.querySelectorAll('#gradeFilterChips button').forEach(btn => {
        btn.classList.remove('bg-emerald-100', 'text-emerald-800');
        btn.classList.add('bg-slate-100', 'text-slate-600');
    });
    event.currentTarget.classList.add('bg-emerald-100', 'text-emerald-800');
    event.currentTarget.classList.remove('bg-slate-100', 'text-slate-600');
    renderStudentsList();
}

function filterStudentsList() {
    renderStudentsList();
}

function renderStudentsList() {
    const container = document.getElementById('studentsListContainer');
    const query = (document.getElementById('studentSearchInput').value || '').trim().toLowerCase();

    let filtered = allStudents.filter(s => {
        const matchesGrade = selectedGradeFilter === 'all' || s.grade.includes(selectedGradeFilter);
        const matchesSearch = !query || s.name.toLowerCase().includes(query) || s.classroom.toLowerCase().includes(query) || (s.national_id && s.national_id.includes(query));
        return matchesGrade && matchesSearch;
    });

    if (filtered.length === 0) {
        container.innerHTML = `
            <div class="text-center py-8 text-slate-400 text-xs">
                <span>🔍 لا يوجد طالب مطابق للبحث</span>
            </div>
        `;
        return;
    }

    container.innerHTML = filtered.map(student => {
        const isSelected = selectedStudent && selectedStudent.id === student.id;
        return `
            <div onclick="selectStudentForReferral(${student.id})" class="p-3 rounded-xl border transition-all cursor-pointer flex items-center justify-between ${
                isSelected 
                ? 'bg-emerald-50 border-emerald-500 shadow-sm ring-2 ring-emerald-500/20' 
                : 'bg-white hover:bg-slate-50 border-slate-200'
            }">
                <div class="flex items-center gap-3">
                    <div class="w-9 h-9 rounded-xl flex items-center justify-center text-sm font-bold ${isSelected ? 'bg-emerald-600 text-white' : 'bg-slate-100 text-slate-700'}">
                        ${student.name.charAt(0)}
                    </div>
                    <div>
                        <div class="font-bold text-xs text-slate-800">${student.name}</div>
                        <div class="text-[11px] text-slate-500">${student.grade} - فصل ${student.classroom}</div>
                    </div>
                </div>
                <div class="text-right">
                    <span class="text-[10px] px-2 py-0.5 rounded-md ${isSelected ? 'bg-emerald-200 text-emerald-900 font-bold' : 'bg-slate-100 text-slate-500'}">
                        ${isSelected ? 'محدد ✓' : 'اختيار'}
                    </span>
                </div>
            </div>
        `;
    }).join('');
}

function selectStudentForReferral(studentId) {
    selectedStudent = allStudents.find(s => s.id === studentId);
    renderStudentsList();

    const card = document.getElementById('selectedStudentCard');
    if (selectedStudent) {
        card.className = "mt-4 p-4 rounded-xl bg-emerald-50 border border-emerald-300 text-right";
        card.innerHTML = `
            <div class="flex items-center justify-between mb-1.5">
                <span class="text-xs font-bold text-emerald-900">الطالب المحدد للإحالة:</span>
                <button type="button" onclick="clearSelectedStudent()" class="text-[11px] text-rose-600 hover:underline">إلغاء التحديد</button>
            </div>
            <div class="text-sm font-bold text-emerald-950">${selectedStudent.name}</div>
            <div class="text-xs text-emerald-700 mt-0.5">${selectedStudent.grade} - فصل ${selectedStudent.classroom}</div>
            ${selectedStudent.guardian_phone ? `<div class="text-[11px] text-emerald-600 mt-1">📞 ولي الأمر: ${selectedStudent.guardian_phone}</div>` : ''}
        `;
    }
}

function clearSelectedStudent() {
    selectedStudent = null;
    renderStudentsList();
    const card = document.getElementById('selectedStudentCard');
    card.className = "mt-4 p-4 rounded-xl bg-slate-50 border border-dashed border-slate-300 text-center text-slate-500";
    card.innerHTML = `
        <span class="text-3xl block mb-1">👤</span>
        <span class="text-xs font-medium">لم يتم تحديد طالب بعد. اختر طالباً من القائمة المقابلة.</span>
    `;
}

// ========================================================
// واجهة المعلم: عرض واختيار السلوكيات
// ========================================================
function filterBehaviorsByDegree() {
    renderBehaviorsList();
}

function renderBehaviorsList() {
    const container = document.getElementById('behaviorsContainer');
    const degreeFilter = document.getElementById('degreeFilterSelect').value;

    let filtered = allBehaviors;
    if (degreeFilter !== 'all') {
        filtered = allBehaviors.filter(b => b.degree === degreeFilter);
    }

    container.innerHTML = filtered.map(b => {
        const isSelected = selectedBehavior && selectedBehavior.id === b.id;
        let badgeColor = 'bg-slate-100 text-slate-700';
        if (b.degree === 'الدرجة الأولى') badgeColor = 'bg-blue-100 text-blue-800';
        if (b.degree === 'الدرجة الثانية') badgeColor = 'bg-amber-100 text-amber-800';
        if (b.degree === 'الدرجة الثالثة') badgeColor = 'bg-orange-100 text-orange-800';
        if (b.degree === 'الدرجة الرابعة') badgeColor = 'bg-rose-100 text-rose-800';
        if (b.degree === 'مخالفة مواظبة') badgeColor = 'bg-purple-100 text-purple-800';

        return `
            <div onclick="selectBehaviorItem(${b.id})" class="p-2.5 rounded-lg border text-right transition cursor-pointer flex items-center justify-between ${
                isSelected 
                ? 'bg-emerald-50 border-emerald-500 shadow-sm' 
                : 'bg-white hover:bg-slate-50 border-slate-200'
            }">
                <div class="flex-1 pl-2">
                    <div class="text-xs font-bold text-slate-800">${b.name}</div>
                    ${b.description ? `<div class="text-[10px] text-slate-400 mt-0.5">${b.description}</div>` : ''}
                </div>
                <div class="flex items-center gap-1.5 flex-shrink-0">
                    <span class="text-[10px] px-2 py-0.5 rounded-md font-bold ${badgeColor}">${b.degree}</span>
                    <input type="radio" name="behaviorRadio" ${isSelected ? 'checked' : ''} class="accent-emerald-600">
                </div>
            </div>
        `;
    }).join('');
}

function selectBehaviorItem(behaviorId) {
    selectedBehavior = allBehaviors.find(b => b.id === behaviorId);
    renderBehaviorsList();
}

// ========================================================
// واجهة المعلم: إرسال الإحالة إلى الوكيل
// ========================================================
async function submitReferral(event) {
    event.preventDefault();

    if (!selectedStudent) {
        showToast('يرجى اختيار الطالب المراد تحويله من القائمة أولاً', 'warning');
        return;
    }

    if (!selectedBehavior) {
        showToast('يرجى اختيار نوع السلوك أو المخالفة المرتكبة', 'warning');
        return;
    }

    const teacherName = document.getElementById('teacherSelect').value;
    if (!teacherName) {
        showToast('يرجى اختيار اسم المعلم', 'warning');
        return;
    }

    const subject = document.getElementById('subjectInput').value;
    const period = document.getElementById('periodSelect').value;
    const notes = document.getElementById('notesInput').value;

    const btn = document.getElementById('submitReferralBtn');
    btn.disabled = true;
    btn.innerHTML = '<span>جاري إرسال الإحالة...</span>';

    try {
        const payload = {
            student_id: selectedStudent.id,
            teacher_name: teacherName,
            subject: subject,
            period: period,
            behavior_id: selectedBehavior.id,
            behavior_name: selectedBehavior.name,
            behavior_degree: selectedBehavior.degree,
            notes: notes
        };

        const res = await fetch('/api/referrals', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!res.ok) throw new Error('فشل إرسال الإحالة');

        const created = await res.json();

        showToast(
            `تم تحويل الطالب ${created.student_name} بنجاح إلى وكيل المدرسة وإشعاره فوراً!`,
            'success',
            'تمت الإحالة بنجاح'
        );

        // إعادة ضبط النموذج
        clearSelectedStudent();
        selectedBehavior = null;
        renderBehaviorsList();
        document.getElementById('notesInput').value = '';

    } catch (e) {
        console.error('Submit referral error:', e);
        showToast('حدث خطأ أثناء الإرسال، تأكد من الاتصال بالخادم', 'urgent');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<span class="text-lg">🚀</span><span>إرسال الإحالة للوكيل فوراً</span>';
    }
}

// ========================================================
// شاشة الوكيل: عرض الإحالات وتصفيتها
// ========================================================
function filterReferralsByStatus(status) {
    currentStatusFilter = status;
    document.querySelectorAll('.ref-filter-btn').forEach(btn => {
        btn.classList.remove('bg-rose-50', 'text-rose-700', 'border', 'border-rose-200', 'bg-slate-200', 'font-bold');
        btn.classList.add('text-slate-600');
    });

    const activeBtn = document.getElementById(`filter-btn-${status}`);
    if (activeBtn) {
        activeBtn.classList.add('bg-slate-200', 'font-bold', 'text-slate-900');
        activeBtn.classList.remove('text-slate-600');
    }

    renderReferralCards();
}

function filterReferralsCards() {
    renderReferralCards();
}

function renderReferralCards() {
    const container = document.getElementById('referralsCardsContainer');
    const query = (document.getElementById('vpSearchInput').value || '').trim().toLowerCase();

    let filtered = allReferrals.filter(r => {
        const matchesStatus = currentStatusFilter === 'all' || r.status === currentStatusFilter;
        const matchesQuery = !query || 
            r.student_name.toLowerCase().includes(query) || 
            r.teacher_name.toLowerCase().includes(query) || 
            r.behavior_name.toLowerCase().includes(query) ||
            r.classroom.toLowerCase().includes(query);
        return matchesStatus && matchesQuery;
    });

    if (filtered.length === 0) {
        container.innerHTML = `
            <div class="bg-white rounded-2xl p-12 text-center border border-slate-200">
                <span class="text-4xl block mb-2">🎉</span>
                <h4 class="text-sm font-bold text-slate-700">لا توجد إحالات في هذه القائمة حالياً</h4>
                <p class="text-xs text-slate-400 mt-1">الوضع منضبط، أو يمكنك تغيير خيارات التصفية بالأعلى</p>
            </div>
        `;
        return;
    }

    container.innerHTML = filtered.map(r => {
        // حالة المعاملة
        let statusBadge = '<span class="px-2.5 py-1 rounded-lg text-xs font-bold bg-rose-100 text-rose-800 border border-rose-200 flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-rose-500 animate-ping"></span> بانتظار الإجراء</span>';
        if (r.status === 'in_progress') {
            statusBadge = '<span class="px-2.5 py-1 rounded-lg text-xs font-bold bg-amber-100 text-amber-800 border border-amber-200 flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-amber-500"></span> قيد المعالجة</span>';
        } else if (r.status === 'resolved') {
            statusBadge = '<span class="px-2.5 py-1 rounded-lg text-xs font-bold bg-emerald-100 text-emerald-800 border border-emerald-200 flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-emerald-500"></span> تم اتخاذ الإجراء</span>';
        }

        // درجة المخالفة
        let degreeBadgeClass = 'bg-slate-100 text-slate-700';
        if (r.behavior_degree === 'الدرجة الأولى') degreeBadgeClass = 'bg-blue-50 text-blue-700 border border-blue-200';
        if (r.behavior_degree === 'الدرجة الثانية') degreeBadgeClass = 'bg-amber-50 text-amber-700 border border-amber-200';
        if (r.behavior_degree === 'الدرجة الثالثة') degreeBadgeClass = 'bg-orange-50 text-orange-700 border border-orange-200';
        if (r.behavior_degree === 'الدرجة الرابعة') degreeBadgeClass = 'bg-rose-50 text-rose-700 border border-rose-200 font-bold';
        if (r.behavior_degree === 'مخالفة مواظبة') degreeBadgeClass = 'bg-purple-50 text-purple-700 border border-purple-200';

        return `
            <div class="bg-white rounded-2xl p-5 border border-slate-200/90 shadow-sm hover:shadow-md transition space-y-4">
                <!-- رأس الكرت: الطالب وتفاصيل الإحالة -->
                <div class="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-b border-slate-100 pb-3">
                    <div class="flex items-center gap-3">
                        <div class="w-11 h-11 rounded-xl bg-gradient-to-br from-emerald-600 to-teal-700 text-white flex items-center justify-center font-bold text-base shadow">
                            ${r.student_name.charAt(0)}
                        </div>
                        <div>
                            <div class="flex items-center gap-2">
                                <h3 class="font-bold text-sm text-slate-900">${r.student_name}</h3>
                                <span class="text-xs text-slate-500 bg-slate-100 px-2 py-0.5 rounded-md">${r.grade} - ${r.classroom}</span>
                            </div>
                            <div class="text-[11px] text-slate-400 mt-0.5 flex items-center gap-2">
                                <span>📅 وقت الإحالة: ${r.created_at || 'الآن'}</span>
                                ${r.period ? `<span>• الحصة: ${r.period}</span>` : ''}
                                ${r.subject ? `<span>• المادة: ${r.subject}</span>` : ''}
                            </div>
                        </div>
                    </div>

                    <div class="flex items-center gap-2 self-end sm:self-auto">
                        ${statusBadge}
                    </div>
                </div>

                <!-- محتوى المخالفة والملاحظات -->
                <div class="bg-slate-50/80 rounded-xl p-3.5 border border-slate-200/60 space-y-2">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center gap-2">
                            <span class="text-xs font-bold text-slate-800">السلوك: ${r.behavior_name}</span>
                        </div>
                        <span class="text-[11px] px-2 py-0.5 rounded-md ${degreeBadgeClass}">${r.behavior_degree}</span>
                    </div>

                    ${r.notes ? `
                        <div class="text-xs text-slate-600 bg-white p-2.5 rounded-lg border border-slate-200/50 leading-relaxed">
                            <strong class="text-slate-700">ملاحظة المعلم (${r.teacher_name}):</strong> ${r.notes}
                        </div>
                    ` : `
                        <div class="text-[11px] text-slate-400">أحال الطالب المعلم: <strong>${r.teacher_name}</strong></div>
                    `}

                    <!-- إذا كان هناك إجراء متخذ سابقاً يظهر هنا -->
                    ${r.action_taken ? `
                        <div class="mt-2 pt-2 border-t border-slate-200 text-xs text-emerald-800 bg-emerald-50/60 p-2.5 rounded-lg border border-emerald-200/60">
                            <div class="font-bold mb-0.5 flex items-center gap-1">
                                <span>🛡️ قرار وإجراء الوكيل:</span>
                                <span class="text-[11px] font-normal text-emerald-700">(${r.action_date || ''})</span>
                            </div>
                            <div>${r.action_taken}</div>
                            ${r.action_notes ? `<div class="text-[11px] text-slate-600 mt-1">تفاصيل إضافية: ${r.action_notes}</div>` : ''}
                        </div>
                    ` : ''}
                </div>

                <!-- أزرار العمليات للوكيل -->
                <div class="flex flex-wrap items-center justify-between gap-2 pt-1">
                    <div class="flex items-center gap-2">
                        <button onclick="viewStudentArchive(${r.student_id})" class="px-3.5 py-2 rounded-xl bg-indigo-50 hover:bg-indigo-100 text-indigo-700 text-xs font-bold flex items-center gap-1.5 transition">
                            <span>📁</span>
                            <span>أرشيف وسجل الطالب السابق</span>
                        </button>
                        <button onclick="printSingleReferral(${r.id})" class="px-3 py-2 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold flex items-center gap-1.5 transition">
                            <span>🖨️</span>
                            <span>استمارة إحالة</span>
                        </button>
                    </div>

                    <div>
                        <button onclick="openActionModal(${r.id})" class="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold flex items-center gap-1.5 shadow transition">
                            <span>✍️</span>
                            <span>${r.status === 'resolved' ? 'تعديل الإجراء' : 'اتخاذ إجراء الآن'}</span>
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

// ========================================================
// أرشيف وسجل الطالب الكامل (Student Archive Modal)
// ========================================================
let currentArchiveData = null;

async function viewStudentArchive(studentId) {
    try {
        const res = await fetch(`/api/students/${studentId}/archive`);
        if (!res.ok) throw new Error('فشل جلب الأرشيف');
        currentArchiveData = await res.json();

        const { student, referrals, stats } = currentArchiveData;

        // تعبئة البيانات
        document.getElementById('archiveStudentName').textContent = student.name;
        document.getElementById('archiveStudentClass').textContent = `${student.grade} - فصل ${student.classroom} ${student.national_id ? `(هوية: ${student.national_id})` : ''}`;

        document.getElementById('archStatTotal').textContent = stats.total_violations;
        document.getElementById('archStatResolved').textContent = stats.resolved;
        document.getElementById('archStatPending').textContent = stats.pending;
        document.getElementById('archStatPoints').textContent = `-${stats.total_deducted_points} د`;

        // بيانات ولي الأمر
        document.getElementById('archivePhoneText').textContent = student.guardian_phone || 'غير مسجل';
        const whatsappLink = document.getElementById('archiveWhatsappLink');
        if (student.guardian_phone) {
            let cleanPhone = student.guardian_phone.replace(/\D/g, '');
            if (cleanPhone.startsWith('05')) cleanPhone = '966' + cleanPhone.substring(1);
            const msg = encodeURIComponent(`السلام عليكم ورحمة الله، المكرم ولي أمر الطالب ${student.name}، نود التواصل معكم بشأن السجل السلوكي لابنكم في المدرسة.`);
            whatsappLink.href = `https://wa.me/${cleanPhone}?text=${msg}`;
            whatsappLink.classList.remove('hidden');
        } else {
            whatsappLink.classList.add('hidden');
        }

        // قائمة السجلات السابقة للطالب
        const listContainer = document.getElementById('archiveHistoryList');
        if (referrals.length === 0) {
            listContainer.innerHTML = `
                <div class="text-center py-10 text-slate-400">
                    <span class="text-4xl block mb-2">🌟</span>
                    <span class="text-sm font-bold text-slate-600">سجل الطالب نظيف تماماً!</span>
                    <p class="text-xs text-slate-400 mt-1">لا توجد أي مخالفات أو إحالات مسجلة على هذا الطالب</p>
                </div>
            `;
        } else {
            listContainer.innerHTML = referrals.map((ref, idx) => `
                <div class="bg-slate-50 rounded-xl p-4 border border-slate-200 space-y-2">
                    <div class="flex items-center justify-between border-b border-slate-200/60 pb-2">
                        <div class="flex items-center gap-2">
                            <span class="w-6 h-6 rounded-full bg-slate-200 text-slate-700 text-xs flex items-center justify-center font-bold">${referrals.length - idx}</span>
                            <span class="text-xs font-bold text-slate-800">${ref.behavior_name}</span>
                        </div>
                        <div class="flex items-center gap-2">
                            <span class="text-[11px] px-2 py-0.5 rounded bg-slate-200 text-slate-700 font-semibold">${ref.behavior_degree}</span>
                            <span class="text-[11px] text-slate-400">📅 ${ref.created_at}</span>
                        </div>
                    </div>

                    <div class="text-xs text-slate-600">
                        <div><strong>المعلم المحيل:</strong> ${ref.teacher_name} ${ref.period ? `(الحصة ${ref.period})` : ''}</div>
                        ${ref.notes ? `<div class="mt-1 bg-white p-2 rounded border border-slate-200/60 text-slate-700"><strong>تفاصيل الواقعة:</strong> ${ref.notes}</div>` : ''}
                    </div>

                    ${ref.action_taken ? `
                        <div class="mt-2 text-xs bg-emerald-50 text-emerald-800 p-2.5 rounded-lg border border-emerald-200">
                            <strong>الإجراء المتخذ من الوكيل:</strong> ${ref.action_taken}
                            ${ref.action_notes ? `<div class="text-[11px] text-slate-600 mt-0.5">ملاحظات: ${ref.action_notes}</div>` : ''}
                        </div>
                    ` : `
                        <div class="text-[11px] text-rose-600 font-semibold">⚠️ بانتظار اتخاذ الإجراء من إدارة المدرسة</div>
                    `}
                </div>
            `).join('');
        }

        document.getElementById('studentArchiveModal').classList.remove('hidden');

    } catch (e) {
        console.error('Archive error:', e);
        showToast('تعذر جلب أرشيف الطالب', 'urgent');
    }
}

function closeArchiveModal() {
    document.getElementById('studentArchiveModal').classList.add('hidden');
}

// ========================================================
// اتخاذ إجراء للوكيل (Action Modal)
// ========================================================
function openActionModal(referralId) {
    const ref = allReferrals.find(r => r.id === referralId);
    if (!ref) return;

    document.getElementById('actionReferralId').value = ref.id;
    document.getElementById('actionModalStudentName').textContent = `${ref.student_name} (${ref.grade} - ${ref.classroom})`;
    document.getElementById('actionModalBehaviorName').textContent = `${ref.behavior_name} (${ref.behavior_degree})`;
    document.getElementById('actionModalTeacherName').textContent = ref.teacher_name;

    if (ref.action_taken) {
        document.getElementById('actionTakenSelect').value = ref.action_taken;
    }
    if (ref.action_notes) {
        document.getElementById('actionNotesInput').value = ref.action_notes;
    }
    document.getElementById('actionStatusSelect').value = ref.status === 'in_progress' ? 'in_progress' : 'resolved';

    document.getElementById('actionModal').classList.remove('hidden');
}

function closeActionModal() {
    document.getElementById('actionModal').classList.add('hidden');
}

async function submitReferralAction(event) {
    event.preventDefault();
    const refId = document.getElementById('actionReferralId').value;
    const actionTaken = document.getElementById('actionTakenSelect').value;
    const actionStatus = document.getElementById('actionStatusSelect').value;
    const actionNotes = document.getElementById('actionNotesInput').value;

    try {
        const res = await fetch(`/api/referrals/${refId}/action`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action_taken: actionTaken,
                action_notes: actionNotes,
                status: actionStatus
            })
        });

        if (!res.ok) throw new Error('فشل تحديث الإجراء');

        closeActionModal();
        await loadReferrals();
        loadStats();
    } catch (e) {
        console.error('Action error:', e);
        showToast('حدث خطأ أثناء حفظ الإجراء', 'urgent');
    }
}

// ========================================================
// دليل الطلاب وإدارتهم (Students Directory)
// ========================================================
function renderStudentsDirectory() {
    const tbody = document.getElementById('studentsDirectoryTableBody');
    const query = (document.getElementById('studentsDirSearch')?.value || '').trim().toLowerCase();

    let filtered = allStudents.filter(s => {
        return !query || 
            s.name.toLowerCase().includes(query) || 
            s.classroom.toLowerCase().includes(query) || 
            s.grade.toLowerCase().includes(query) || 
            (s.national_id && s.national_id.includes(query));
    });

    if (filtered.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" class="p-6 text-center text-slate-400 text-xs">لا يوجد طلاب مطابقين للبحث</td></tr>`;
        return;
    }

    tbody.innerHTML = filtered.map(s => `
        <tr class="hover:bg-slate-50 transition border-b border-slate-100">
            <td class="p-3.5 font-bold text-slate-900">${s.name}</td>
            <td class="p-3.5 text-slate-600">${s.grade} - ${s.classroom}</td>
            <td class="p-3.5 font-mono text-slate-500 text-xs">${s.national_id || '-'}</td>
            <td class="p-3.5 font-mono text-slate-600 text-xs">${s.guardian_phone || '-'}</td>
            <td class="p-3.5 text-center">
                <button onclick="viewStudentArchive(${s.id})" class="px-3 py-1.5 rounded-lg bg-indigo-50 hover:bg-indigo-100 text-indigo-700 text-xs font-bold transition">
                    📁 فتح الأرشيف
                </button>
            </td>
        </tr>
    `).join('');
}

function filterStudentsDirectory() {
    renderStudentsDirectory();
}

// إضافة طالب جديد
function openNewStudentModal() {
    document.getElementById('newStudentModal').classList.remove('hidden');
}

function closeNewStudentModal() {
    document.getElementById('newStudentModal').classList.add('hidden');
}

async function submitNewStudent(event) {
    event.preventDefault();
    const name = document.getElementById('newStudentName').value;
    const grade = document.getElementById('newStudentGrade').value;
    const classroom = document.getElementById('newStudentClassroom').value;
    const natId = document.getElementById('newStudentNatId').value;
    const phone = document.getElementById('newStudentPhone').value;

    try {
        const res = await fetch('/api/students', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                grade: grade,
                classroom: classroom,
                national_id: natId,
                guardian_phone: phone
            })
        });

        if (!res.ok) throw new Error('فشل إضافة الطالب');

        showToast(`تمت إضافة الطالب ${name} بنجاح`, 'success');
        closeNewStudentModal();
        document.getElementById('newStudentForm').reset();
        await loadStudents();
    } catch (e) {
        console.error('Add student error:', e);
        showToast('تعذر حفظ بيانات الطالب', 'urgent');
    }
}

// استيراد ملف الطلاب من نور
function openImportModal() {
    document.getElementById('importModal').classList.remove('hidden');
}

function closeImportModal() {
    document.getElementById('importModal').classList.add('hidden');
}

function handleFileSelect(event) {
    const file = event.target.files[0];
    if (file) {
        document.getElementById('selectedFileName').textContent = `الملف المختار: ${file.name} (${Math.round(file.size / 1024)} كيلوبايت)`;
    }
}

async function submitImportCsv(event) {
    event.preventDefault();
    const fileInput = document.getElementById('csvFileInput');
    if (!fileInput.files || fileInput.files.length === 0) {
        showToast('يرجى اختيار ملف CSV أولاً', 'warning');
        return;
    }

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);

    const btn = document.getElementById('importSubmitBtn');
    btn.disabled = true;
    btn.textContent = 'جاري قراءة الملف والاستيراد...';

    try {
        const res = await fetch('/api/students/import-csv', {
            method: 'POST',
            body: formData
        });

        const data = await res.json();
        showToast(data.message, 'success', 'اكتمل الاستيراد');
        closeImportModal();
        await loadStudents();
        loadStats();
    } catch (e) {
        console.error('Import error:', e);
        showToast('حدث خطأ أثناء استيراد الملف', 'urgent');
    } finally {
        btn.disabled = false;
        btn.textContent = 'بدء الاستيراد';
    }
}

// ========================================================
// الطباعة الرسمية (Print Slip)
// ========================================================
function printSingleReferral(referralId) {
    const ref = allReferrals.find(r => r.id === referralId);
    if (!ref) return;

    const printContainer = document.getElementById('printContainer');
    printContainer.innerHTML = `
        <div style="direction: rtl; font-family: 'Tajawal', sans-serif; max-width: 800px; margin: 0 auto; border: 2px solid #000; padding: 30px; border-radius: 8px;">
            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #333; padding-bottom: 15px; margin-bottom: 20px;">
                <div style="font-size: 13px; line-height: 1.6;">
                    <strong>المملكة العربية السعودية</strong><br>
                    وزارة التعليم<br>
                    إدارة التعليم<br>
                    المدرسة / وكالة شؤون الطلاب
                </div>
                <div style="text-align: center;">
                    <h2 style="font-size: 20px; font-weight: bold; margin: 0;">استمارة إحالة طالب لوكيل المدرسة</h2>
                    <span style="font-size: 12px; color: #555;">رقم الإحالة: #${ref.id}</span>
                </div>
                <div style="font-size: 13px; text-align: left;">
                    التاريخ: ${ref.created_at ? ref.created_at.split(' ')[0] : ''}<br>
                    الحصة: ${ref.period || 'الأولى'}
                </div>
            </div>

            <div style="margin-bottom: 20px; font-size: 14px; line-height: 2;">
                <table style="width: 100%; border-collapse: collapse; margin-bottom: 15px;">
                    <tr>
                        <td style="border: 1px solid #999; padding: 8px; width: 50%;"><strong>اسم الطالب:</strong> ${ref.student_name}</td>
                        <td style="border: 1px solid #999; padding: 8px;"><strong>الصف والفصل:</strong> ${ref.grade} - ${ref.classroom}</td>
                    </tr>
                    <tr>
                        <td style="border: 1px solid #999; padding: 8px;"><strong>المعلم المحيل:</strong> ${ref.teacher_name}</td>
                        <td style="border: 1px solid #999; padding: 8px;"><strong>المادة:</strong> ${ref.subject || 'عام'}</td>
                    </tr>
                </table>

                <div style="border: 1px solid #999; padding: 12px; border-radius: 4px; margin-bottom: 15px; background-color: #fafafa;">
                    <strong>السلوك المرتكب:</strong> ${ref.behavior_name} (${ref.behavior_degree})<br>
                    <strong>تفاصيل وملاحظات المعلم:</strong> ${ref.notes || 'لا توجد ملاحظات إضافية'}
                </div>

                <div style="border: 1px solid #000; padding: 15px; border-radius: 4px; background-color: #fff; min-height: 100px;">
                    <strong style="text-decoration: underline;">قرار وإجراء وكيل شؤون الطلاب:</strong><br>
                    <div style="margin-top: 8px;">${ref.action_taken || '__________________________________________________________________'}</div>
                    <div style="margin-top: 6px; font-size: 13px; color: #444;">${ref.action_notes || ''}</div>
                </div>
            </div>

            <div style="display: flex; justify-content: space-between; margin-top: 40px; padding-top: 20px;">
                <div style="text-align: center; width: 30%;">
                    <strong>توقيع المعلم المحيل</strong><br><br><br>
                    ...................................
                </div>
                <div style="text-align: center; width: 30%;">
                    <strong>توقيع الطالب بالعلم</strong><br><br><br>
                    ...................................
                </div>
                <div style="text-align: center; width: 30%;">
                    <strong>وكيل شؤون الطلاب</strong><br><br><br>
                    ...................................
                </div>
            </div>
        </div>
    `;

    window.print();
}

function printStudentArchive() {
    if (!currentArchiveData) return;
    const { student, referrals, stats } = currentArchiveData;

    const printContainer = document.getElementById('printContainer');
    printContainer.innerHTML = `
        <div style="direction: rtl; font-family: 'Tajawal', sans-serif; max-width: 850px; margin: 0 auto; border: 2px solid #000; padding: 30px;">
            <div style="text-align: center; border-bottom: 2px solid #333; padding-bottom: 15px; margin-bottom: 20px;">
                <h2 style="font-size: 22px; font-weight: bold; margin: 0;">تقرير السجل والأرشيف السلوكي الشامل للطالب</h2>
                <p style="font-size: 14px; margin-top: 5px;">وزارة التعليم - إدارة المدرسة - وكالة شؤون الطلاب</p>
            </div>

            <div style="background: #f4f4f4; padding: 15px; border-radius: 6px; margin-bottom: 20px; font-size: 14px;">
                <strong>اسم الطالب:</strong> ${student.name} &nbsp;&nbsp;|&nbsp;&nbsp;
                <strong>الصف:</strong> ${student.grade} - فصل ${student.classroom} &nbsp;&nbsp;|&nbsp;&nbsp;
                <strong>السجل المدني:</strong> ${student.national_id || '-'} &nbsp;&nbsp;|&nbsp;&nbsp;
                <strong>جوال ولي الأمر:</strong> ${student.guardian_phone || '-'}
            </div>

            <div style="margin-bottom: 20px; font-size: 13px;">
                <strong>ملخص المخالفات:</strong> إجمالي الإحالات: (${stats.total_violations}) | المنتهية: (${stats.resolved}) | درجات السلوك المخصومة: (${stats.total_deducted_points} درجات)
            </div>

            <table style="width: 100%; border-collapse: collapse; font-size: 12px;">
                <thead>
                    <tr style="background: #e2e8f0;">
                        <th style="border: 1px solid #999; padding: 8px;">م</th>
                        <th style="border: 1px solid #999; padding: 8px;">التاريخ</th>
                        <th style="border: 1px solid #999; padding: 8px;">المعلم</th>
                        <th style="border: 1px solid #999; padding: 8px;">السلوك والدرجة</th>
                        <th style="border: 1px solid #999; padding: 8px;">ملاحظات الواقعة</th>
                        <th style="border: 1px solid #999; padding: 8px;">الإجراء المتخذ</th>
                    </tr>
                </thead>
                <tbody>
                    ${referrals.map((r, i) => `
                        <tr>
                            <td style="border: 1px solid #999; padding: 6px; text-align: center;">${i + 1}</td>
                            <td style="border: 1px solid #999; padding: 6px;">${r.created_at ? r.created_at.split(' ')[0] : ''}</td>
                            <td style="border: 1px solid #999; padding: 6px;">${r.teacher_name}</td>
                            <td style="border: 1px solid #999; padding: 6px;">${r.behavior_name}<br><small style="color: #666;">(${r.behavior_degree})</small></td>
                            <td style="border: 1px solid #999; padding: 6px;">${r.notes || '-'}</td>
                            <td style="border: 1px solid #999; padding: 6px;">${r.action_taken || 'قيد المتابعة'}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>

            <div style="display: flex; justify-content: space-between; margin-top: 50px; font-size: 13px;">
                <div style="text-align: center;"><strong>الموجه الطلابي</strong><br><br>.............................</div>
                <div style="text-align: center;"><strong>وكيل شؤون الطلاب</strong><br><br>.............................</div>
                <div style="text-align: center;"><strong>مدير المدرسة</strong><br><br>.............................</div>
            </div>
        </div>
    `;

    window.print();
}

// ========================================================
// بدء تشغيل التطبيق عند تحميل الصفحة
// ========================================================
window.addEventListener('DOMContentLoaded', () => {
    initWebSocket();
    loadInitialData();
});
