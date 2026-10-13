/* NTXP Admin — synthetic demo data and in-memory API.
   Employee names are fictional. Only the two owners are real people. */
(function () {
  "use strict";

  const DAY = 86400000;
  const NOW = new Date("2026-10-09T15:20:00-05:00").getTime();
  const iso = (offsetDays, hour) => {
    const d = new Date(NOW - offsetDays * DAY);
    if (hour != null) d.setHours(hour, (offsetDays * 17) % 60, 0, 0);
    return d.toISOString();
  };
  const isoDate = (offsetDays) => iso(offsetDays).slice(0, 10);
  const clone = (x) => JSON.parse(JSON.stringify(x));
  const jev = (tier, cost, executor) => ({ tier, executor: executor || (tier === 0 ? "script" : tier === 1 ? "deepseek" : "claude"), cost });

  /* ---------- Identity ---------- */
  const me = { email: "trevor@ntxpllc.com", name: "Trevor Hopkins", role: "owner" };
  const health = {
    sources: { gmail: "ok", drive: "ok", calendar: "ok", contacts: "ok", directory: "ok", reports: "ok",
               jobtread: "ok", plaud: "unconfigured", quo: "ok", council: "ok", sheets_db: "error" },
    demo: true,
  };

  const actions = [
    { id: "red_flags", title: "Review open red flags", blurb: "Escalated issues across mail, JobTread and calls that need an owner decision.", module: "analytics", icon: "flag" },
    { id: "find_message", title: "Find a message", blurb: "Describe it in plain words; search every NTXP mailbox and Drive.", module: "search", icon: "search" },
    { id: "unanswered", title: "Unanswered client emails", blurb: "Client threads waiting more than one business day for a reply.", module: "analytics", icon: "mail" },
    { id: "billing_q", title: "Open billing questions", blurb: "Pay-app and invoice questions from owners and subs still unresolved.", module: "analytics", icon: "dollar" },
    { id: "share_contact", title: "Share a contact with the team", blurb: "Push a client or sub into the IPDM shared address book.", module: "contacts", icon: "users" },
    { id: "import_contacts", title: "Import contacts", blurb: "Bring in a vCard or Google / Outlook CSV with a duplicate check.", module: "contacts", icon: "upload" },
    { id: "response_time", title: "Check response times", blurb: "Median reply time per person against the four-hour target.", module: "analytics", icon: "clock" },
    { id: "stuck_workflow", title: "Unstick a workflow", blurb: "Runbook steps for pay apps, submittals, intake and sync jobs.", module: "runbook", icon: "book" },
    { id: "user_access", title: "Suspend or restore a user", blurb: "Workspace sign-in, suspension and Drive transfer with approval.", module: "workspace", icon: "shield" },
    { id: "external_files", title: "Externally shared files", blurb: "Find Drive files shared outside ntxpllc.com and who owns them.", module: "workspace", icon: "share" },
  ];

  /* ---------- People ---------- */
  const staff = [
    { email: "alison@ntxpllc.com", name: "Alison Hopkins", role: "Owner" },
    { email: "trevor@ntxpllc.com", name: "Trevor Hopkins", role: "Operations Contact" },
    { email: "marcus.delgado@ntxpllc.com", name: "Marcus Delgado", role: "Project Manager" },
    { email: "renee.whitfield@ntxpllc.com", name: "Renee Whitfield", role: "Senior Estimator" },
    { email: "jalen.brooks@ntxpllc.com", name: "Jalen Brooks", role: "Superintendent" },
    { email: "priya.natarajan@ntxpllc.com", name: "Priya Natarajan", role: "Project Coordinator" },
    { email: "cole.ashby@ntxpllc.com", name: "Cole Ashby", role: "Field Supervisor" },
    { email: "dana.okafor@ntxpllc.com", name: "Dana Okafor", role: "Accounts & Billing" },
    { email: "luis.herrera@ntxpllc.com", name: "Luis Herrera", role: "Foreman" },
    { email: "tessa.varga@ntxpllc.com", name: "Tessa Varga", role: "Assistant PM" },
  ];
  const first = (email) => (staff.find((s) => s.email === email) || { name: email }).name.split(" ")[0];
  const fullName = (email) => (staff.find((s) => s.email === email) || { name: email }).name;

  const people = [
    { email: "marcus.delgado@ntxpllc.com", name: "Marcus Delgado", role: "Project Manager", response_hrs: 2.6, unanswered: 1, baseline_dev: -0.12, open_flags: 0, top_level: 0 },
    { email: "renee.whitfield@ntxpllc.com", name: "Renee Whitfield", role: "Senior Estimator", response_hrs: 3.1, unanswered: 2, baseline_dev: 0.05, open_flags: 1, top_level: 1 },
    { email: "jalen.brooks@ntxpllc.com", name: "Jalen Brooks", role: "Superintendent", response_hrs: 7.8, unanswered: 4, baseline_dev: 0.62, open_flags: 2, top_level: 3 },
    { email: "priya.natarajan@ntxpllc.com", name: "Priya Natarajan", role: "Project Coordinator", response_hrs: 1.4, unanswered: 0, baseline_dev: -0.31, open_flags: 0, top_level: 0 },
    { email: "cole.ashby@ntxpllc.com", name: "Cole Ashby", role: "Field Supervisor", response_hrs: 5.2, unanswered: 3, baseline_dev: 0.28, open_flags: 1, top_level: 2 },
    { email: "dana.okafor@ntxpllc.com", name: "Dana Okafor", role: "Accounts & Billing", response_hrs: 3.9, unanswered: 1, baseline_dev: 0.09, open_flags: 1, top_level: 2 },
    { email: "luis.herrera@ntxpllc.com", name: "Luis Herrera", role: "Foreman", response_hrs: 6.1, unanswered: 2, baseline_dev: 0.18, open_flags: 0, top_level: 0 },
    { email: "tessa.varga@ntxpllc.com", name: "Tessa Varga", role: "Assistant PM", response_hrs: 2.2, unanswered: 0, baseline_dev: -0.08, open_flags: 1, top_level: 1 },
  ];

  /* ---------- Tiles ---------- */
  const tiles = [
    { id: "response_time", label: "Median response time", value: 3.4, unit: "h", display: "3.4", target: 4, trend: -0.8, status: "good", kind: "gauge",
      breakdown: [{ label: "Priya", value: 1.4 }, { label: "Tessa", value: 2.2 }, { label: "Marcus", value: 2.6 }, { label: "Renee", value: 3.1 }, { label: "Dana", value: 3.9 }, { label: "Cole", value: 5.2 }, { label: "Luis", value: 6.1 }, { label: "Jalen", value: 7.8 }], report_id: "response_time" },
    { id: "unanswered_email", label: "Unanswered client emails", value: 13, unit: "", display: "13", target: 5, trend: 4, status: "bad", kind: "bar",
      breakdown: [{ label: "Jalen", value: 4 }, { label: "Cole", value: 3 }, { label: "Renee", value: 2 }, { label: "Luis", value: 2 }, { label: "Marcus", value: 1 }, { label: "Dana", value: 1 }], report_id: "unanswered_email" },
    { id: "wait_complaints", label: "Client wait complaints · 30d", value: 7, unit: "", display: "7", target: 3, trend: 2, status: "watch", kind: "pie",
      breakdown: [{ label: "Email", value: 3 }, { label: "Phone (Quo)", value: 2 }, { label: "OAC meeting", value: 1 }, { label: "JobTread", value: 1 }], report_id: "wait_complaints" },
    { id: "no_shows", label: "Meeting attendance", value: 94, unit: "%", display: "94", target: 95, trend: -1.5, status: "watch", kind: "ring",
      breakdown: [{ label: "Attended", value: 47 }, { label: "No-show", value: 2 }, { label: "Late > 10 min", value: 1 }], report_id: "no_shows" },
    { id: "responsiveness_anomaly", label: "Responsiveness anomaly index", value: 31, unit: "", display: "31", target: 25, trend: 9, status: "watch", kind: "gauge",
      breakdown: [{ label: "Jalen", value: 62 }, { label: "Cole", value: 28 }, { label: "Luis", value: 18 }], report_id: "responsiveness_anomaly" },
    { id: "project_folder_access", label: "Project folder compliance", value: 88, unit: "%", display: "88", target: 95, trend: 3, status: "watch", kind: "ring",
      breakdown: [{ label: "Correct structure", value: 22 }, { label: "Misfiled", value: 2 }, { label: "Over-shared", value: 1 }], report_id: "project_folder_access" },
    { id: "daily_report_quality", label: "Daily report quality", value: 82, unit: "/100", display: "82", target: 85, trend: 2.5, status: "watch", kind: "gauge",
      breakdown: [{ label: "Jalen", value: 71 }, { label: "Cole", value: 84 }, { label: "Luis", value: 88 }], report_id: "daily_report_quality" },
    { id: "po_invoice_integrity", label: "PO ↔ invoice match", value: 97, unit: "%", display: "97", target: 98, trend: 0.6, status: "good", kind: "ring",
      breakdown: [{ label: "Matched", value: 116 }, { label: "Variance", value: 3 }, { label: "Missing PO", value: 1 }], report_id: "po_invoice_integrity" },
    { id: "open_billing_questions", label: "Open billing questions", value: 6, unit: "", display: "6", target: 3, trend: 1, status: "bad", kind: "pie",
      breakdown: [{ label: "Pay app G703", value: 3 }, { label: "Retainage", value: 1 }, { label: "Change order", value: 1 }, { label: "Sub invoice", value: 1 }], report_id: "open_billing_questions" },
    { id: "cross_channel_confirmation", label: "Cross-channel confirmation", value: 78, unit: "%", display: "78", target: 85, trend: -4, status: "watch", kind: "bar",
      breakdown: [{ label: "Gmail", value: 91 }, { label: "JobTread", value: 82 }, { label: "Calendar", value: 76 }, { label: "Quo", value: 64 }, { label: "Plaud", value: 58 }], report_id: "cross_channel_confirmation" },
  ];
  let summaryUpdated = iso(0);

  /* ---------- Flags ---------- */
  const flags = [
    { id: "FL-2026-10-09-001", person: "jalen.brooks@ntxpllc.com", kpi: "unanswered_email", level: 3, urgency: "critical", channel: "gmail", severity: "redflag",
      confidence: 0.91, volatility: 0.64,
      summary: "Four client threads from North Prairie ISD unanswered for 3+ business days, including an RFI on the gym roof drain tie-in.",
      evidence: [
        { source: "gmail", ref: "thread 18f2c9a1 · RFI-014 roof drain tie-in", note: "Client follow-up sent twice; no reply from Jalen." },
        { source: "jobtread", ref: "Job 2417 · Daily log 10/07", note: "Daily log mentions drain conflict but no RFI response logged." },
        { source: "quo", ref: "Call 10/08 14:12 · 2m 40s", note: "Missed inbound call from client facilities lead." },
      ],
      crosscheck: { status: "confirmed", sources_checked: ["gmail", "jobtread", "calendar", "quo"],
                    explanations: ["No PTO or site-only day on calendar for 10/06–10/08.", "No reply sent from phone or JobTread messaging either."] },
      council: { council_id: "CNC-7731", agreement: 0.83, conclusion: "Pattern is real, not a data gap. Recommend owner call today and reassign RFI-014 to Marcus until cleared." },
      created: iso(0, 7), status: "open",
      escalations: [
        { level: 1, channel: "daily_note", at: iso(2, 7), to: ["trevor@ntxpllc.com"] },
        { level: 2, channel: "email", at: iso(1, 7), to: ["trevor@ntxpllc.com"] },
        { level: 3, channel: "sms", at: iso(0, 7), to: ["trevor@ntxpllc.com", "alison@ntxpllc.com"] },
      ] },
    { id: "FL-2026-10-09-002", person: "dana.okafor@ntxpllc.com", kpi: "po_invoice_integrity", level: 2, urgency: "high", channel: "quickbooks", severity: "issue",
      confidence: 0.78, volatility: 0.12,
      summary: "Sub invoice from Brazos Roofing exceeds PO 2417-07 by $4,860 with no approved change order on file.",
      evidence: [
        { source: "quickbooks", ref: "Bill 30551 · Brazos Roofing", note: "Billed $38,860 against PO value $34,000." },
        { source: "drive", ref: "2417 / 06 Change Orders", note: "No CO document dated after 09/15." },
      ],
      crosscheck: { status: "inconclusive", sources_checked: ["quickbooks", "drive", "gmail"],
                    explanations: ["An email from the sub references 'added flashing per field direction' but no written direction was found."] },
      council: { council_id: "CNC-7729", agreement: 0.67, conclusion: "Hold payment on the variance; request the field direction and a CO before releasing." },
      created: iso(1, 9), status: "open",
      escalations: [{ level: 1, channel: "daily_note", at: iso(1, 9), to: ["trevor@ntxpllc.com"] }, { level: 2, channel: "email", at: iso(0, 9), to: ["trevor@ntxpllc.com", "alison@ntxpllc.com"] }] },
    { id: "FL-2026-10-08-004", person: "cole.ashby@ntxpllc.com", kpi: "daily_report_quality", level: 2, urgency: "medium", channel: "jobtread", severity: "concern",
      confidence: 0.72, volatility: 0.21,
      summary: "Three of five daily reports this week lack manpower counts and photos for Cedar Hollow Library.",
      evidence: [{ source: "jobtread", ref: "Job 2431 · Daily logs 10/05–10/09", note: "Manpower field blank on 3 logs; 0 photos attached." }],
      crosscheck: { status: "explained", sources_checked: ["jobtread", "plaud"], explanations: ["Plaud recording 10/06 shows crew counts were read aloud on site; data exists but was not transcribed."] },
      council: null, created: iso(1, 16), status: "ack",
      escalations: [{ level: 1, channel: "daily_note", at: iso(1, 16), to: ["trevor@ntxpllc.com"] }] },
    { id: "FL-2026-10-08-002", person: "renee.whitfield@ntxpllc.com", kpi: "wait_complaints", level: 1, urgency: "low", channel: "gmail", severity: "note",
      confidence: 0.58, volatility: 0.08,
      summary: "Client noted the revised estimate for Elm Fork Fire Station 3 took a week; within contract terms.",
      evidence: [{ source: "gmail", ref: "thread 18f1a0de · Re: revised scope pricing", note: "\"Took a little longer than hoped\" — courteous tone." }],
      crosscheck: { status: "explained", sources_checked: ["gmail", "calendar"], explanations: ["Revision required a site walk scheduled by the client on 10/03."] },
      council: null, created: iso(1, 11), status: "open",
      escalations: [{ level: 1, channel: "daily_note", at: iso(1, 11), to: ["trevor@ntxpllc.com"] }] },
    { id: "FL-2026-10-07-003", person: "tessa.varga@ntxpllc.com", kpi: "project_folder_access", level: 1, urgency: "medium", channel: "drive", severity: "concern",
      confidence: 0.81, volatility: 0,
      summary: "Submittal folder for job 2417 shared as 'anyone with the link' to an external reviewer.",
      evidence: [{ source: "drive", ref: "2417 / 04 Submittals", note: "Link sharing enabled 10/06 by Tessa." }],
      crosscheck: { status: "pending", sources_checked: ["drive"], explanations: [] },
      council: null, created: iso(2, 10), status: "open",
      escalations: [{ level: 1, channel: "daily_note", at: iso(2, 10), to: ["trevor@ntxpllc.com"] }] },
    { id: "FL-2026-10-06-001", person: "luis.herrera@ntxpllc.com", kpi: "no_shows", level: 1, urgency: "low", channel: "calendar", severity: "note",
      confidence: 0.64, volatility: 0.05,
      summary: "Missed the 10/06 pre-pour coordination call.",
      evidence: [{ source: "calendar", ref: "Event 10/06 07:00 · Pre-pour", note: "Accepted, did not join." }],
      crosscheck: { status: "explained", sources_checked: ["calendar", "quo"], explanations: ["Quo log shows Luis called the super at 06:58 from site instead."] },
      council: null, created: iso(3, 8), status: "resolved",
      escalations: [{ level: 1, channel: "daily_note", at: iso(3, 8), to: ["trevor@ntxpllc.com"] }] },
  ];

  /* ---------- Reports ---------- */
  const REPORT_TEXT = {
    response_time: {
      title: "Median Response Time — Staff Email",
      sources: ["gmail", "calendar", "quo"],
      sections: [
        { heading: "Overview", findings: ["Median first-reply time across eight staff mailboxes fell from 4.2 h to 3.4 h over the last 14 days.", "Two field roles (Superintendent, Foreman) remain above the 4-hour target."],
          evidence: [{ source: "gmail", ref: "1,284 inbound client threads", note: "Business hours only, 7a–6p Central." }] },
        { heading: "Outliers", findings: ["Jalen Brooks: 7.8 h median, 62% above his own 90-day baseline.", "Luis Herrera: 6.1 h, consistent with site-heavy weeks."],
          evidence: [{ source: "calendar", ref: "Site blocks 10/01–10/09", note: "Luis on site 9 of 9 days; Jalen 4 of 9." }, { source: "quo", ref: "Call logs", note: "Jalen phone replies did not offset the email gap." }] },
      ],
      conclusions: [{ text: "Team-wide response time is healthy and improving.", confidence: 0.9, council_id: null }, { text: "Jalen's delay is behavioral, not workload-driven; a direct conversation is warranted.", confidence: 0.74, council_id: "CNC-7731" }],
    },
    unanswered_email: {
      title: "Unanswered Client Emails",
      sources: ["gmail", "jobtread"],
      sections: [
        { heading: "Open threads", findings: ["13 client threads have no NTXP reply after one business day.", "6 of 13 belong to North Prairie ISD (job 2417)."],
          evidence: [{ source: "gmail", ref: "Label: client/*", note: "Threads where the last message is from an external sender." }] },
        { heading: "Risk", findings: ["One thread contains an open RFI with a schedule impact (RFI-014)."],
          evidence: [{ source: "jobtread", ref: "Job 2417 · RFI log", note: "RFI-014 due 10/08." }] },
      ],
      conclusions: [{ text: "Reassign RFI-014 today to protect the roof schedule.", confidence: 0.86, council_id: "CNC-7731" }],
    },
  };
  function buildReport(id) {
    const tile = tiles.find((t) => t.report_id === id);
    const base = REPORT_TEXT[id] || {
      title: tile ? tile.label : id,
      sources: ["gmail", "jobtread", "drive"],
      sections: [
        { heading: "Current reading", findings: [`${tile ? tile.label : id} is ${tile ? tile.display + (tile.unit || "") : "n/a"} against a target of ${tile ? tile.target + (tile.unit || "") : "n/a"}.`,
          `Status is "${tile ? tile.status : "watch"}" with a ${tile && tile.trend >= 0 ? "rise" : "drop"} of ${tile ? Math.abs(tile.trend) : 0} over the prior period.`],
          evidence: (tile ? tile.breakdown : []).map((b) => ({ source: "analytics", ref: b.label, note: `Value ${b.value}` })) },
        { heading: "Drivers", findings: ["The largest share comes from the top two contributors in the breakdown.", "No data-source outage affected this period."],
          evidence: [{ source: "sheets_db", ref: "02 Scores tab", note: "Nightly scoring run completed 05:10." }] },
      ],
      conclusions: [{ text: "Keep on the weekly owner review until it returns to target.", confidence: 0.7, council_id: null }],
    };
    return Object.assign({ id, generated: iso(0), period: { from: isoDate(14), to: isoDate(0) }, jev: jev(2, 0.04) }, clone(base));
  }

  /* ---------- Contacts ---------- */
  const orgs = ["North Prairie ISD", "Brazos Roofing Co.", "Trinity Mechanical", "Lone Star Electric", "Elm Fork Plumbing", "Cedar Hollow Library", "Red Oak Architects", "Pecan Valley Concrete", "Blackland Engineering", "Mesquite Glass & Glazing"];
  const titles = ["Facilities Director", "Project Manager", "Estimator", "Owner", "Superintendent", "Purchasing Agent", "Principal Architect", "Office Manager", "Field Engineer", "Controller"];
  const names = [["Avery", "Caldwell"], ["Bianca", "Ruiz"], ["Calvin", "Mercer"], ["Delia", "Fontaine"], ["Ethan", "Pruitt"], ["Farah", "Siddiqui"], ["Gideon", "Lowe"], ["Harper", "Quinlan"], ["Isaac", "Moreno"], ["June", "Albright"],
                 ["Kendra", "Batiste"], ["Levi", "Hargrove"], ["Mina", "Takeda"], ["Nolan", "Price"], ["Opal", "Jennings"], ["Pierce", "Vance"], ["Quincy", "Rhodes"], ["Rosa", "Villareal"], ["Silas", "Dunmore"], ["Talia", "Greer"],
                 ["Uriel", "Castro"], ["Vera", "Lindqvist"], ["Wade", "Holloway"], ["Ximena", "Paredes"], ["Yusuf", "Bello"], ["Zoe", "Kincaid"], ["Abel", "Stroud"], ["Brynn", "Mattox"], ["Cyrus", "Oyelaran"], ["Dahlia", "Pratt"]];
  const owners = ["trevor@ntxpllc.com", "alison@ntxpllc.com", "marcus.delgado@ntxpllc.com", "renee.whitfield@ntxpllc.com", "priya.natarajan@ntxpllc.com"];
  const contacts = [];
  names.forEach(([g, f], i) => {
    const org = orgs[i % orgs.length];
    const dom = org.toLowerCase().replace(/[^a-z]+/g, "").slice(0, 14) + ".example";
    const shared = i % 3 === 0;
    const source = shared && i % 2 === 0 ? "shared" : "workspace";
    contacts.push({
      id: (source === "shared" ? "sh:" : "ws:people/c") + (4100 + i),
      source, name: `${g} ${f}`, given: g, family: f,
      emails: [`${g.toLowerCase()}.${f.toLowerCase()}@${dom}`], phones: [`(214) 555-${String(1000 + i * 37).slice(-4)}`],
      org, title: titles[i % titles.length], address: i % 4 === 0 ? `${200 + i * 11} Industrial Blvd, Denton, TX 76201` : "",
      notes: i % 5 === 0 ? "Prefers text before site visits." : "", labels: shared ? ["★ NTXP Shared", i % 2 ? "Subcontractor" : "Client"] : (i % 2 ? ["Subcontractor"] : ["Client"]),
      shared, owner_user: owners[i % owners.length], updated: iso(i % 20, 10),
    });
  });
  staff.forEach((s, i) => {
    const [g, ...rest] = s.name.split(" ");
    contacts.push({
      id: "dir:" + s.email, source: "directory", name: s.name, given: g, family: rest.join(" "), emails: [s.email],
      phones: s.email === "alison@ntxpllc.com" || s.email === "trevor@ntxpllc.com" ? ["469-248-7431"] : [`(469) 555-${String(2100 + i * 13).slice(-4)}`],
      org: "NTXP LLC", title: s.role, address: "101 South Locust St Ste 605, Denton, TX 76201", notes: "", labels: ["Staff"],
      shared: true, owner_user: "directory", updated: iso(30 + i),
    });
  });
  let contactSeq = 5000;

  /* ---------- Search corpus ---------- */
  const messages = [
    ["jalen.brooks@ntxpllc.com", "avery.caldwell@northprairieisd.example", "RFI-014 — gym roof drain tie-in", "Following up again on the drain tie-in at grid C/7. We need a direction before Friday's pour.", 1, "North Prairie ISD Gym Reroof"],
    ["dana.okafor@ntxpllc.com", "billing@brazosroofing.example", "Invoice 30551 variance vs PO 2417-07", "The invoice is $4,860 over the PO. Can you send the field direction for the added flashing?", 1, "North Prairie ISD Gym Reroof"],
    ["marcus.delgado@ntxpllc.com", "delia.fontaine@redoakarchitects.example", "ASI-03 storefront revisions", "Attached is ASI-03 with the revised storefront elevations and hardware schedule.", 3, "Cedar Hollow Library"],
    ["renee.whitfield@ntxpllc.com", "gideon.lowe@elmforkfire.example", "Revised scope pricing — Fire Station 3", "Here is the revised pricing after the site walk. Line items 14–22 updated.", 6, "Elm Fork Fire Station 3"],
    ["priya.natarajan@ntxpllc.com", "submittals@trinitymech.example", "Submittal 23 05 00-02 returned", "Returned as Revise and Resubmit. Please address the vibration isolation comments.", 4, "Cedar Hollow Library"],
    ["cole.ashby@ntxpllc.com", "trevor@ntxpllc.com", "Daily report 10/07 — Cedar Hollow", "Crew of 9 on site, framing level 2 complete, inspection booked Thursday.", 2, "Cedar Hollow Library"],
    ["trevor@ntxpllc.com", "harper.quinlan@lonestarelectric.example", "Pay app #4 backup", "Please send lien waivers and the updated G703 before we submit pay app #4.", 5, "North Prairie ISD Gym Reroof"],
    ["tessa.varga@ntxpllc.com", "mina.takeda@blacklandeng.example", "Structural review — mezzanine", "The engineer of record signed off on the mezzanine connection detail.", 8, "Cedar Hollow Library"],
    ["alison@ntxpllc.com", "kendra.batiste@northprairieisd.example", "Board presentation — schedule recovery", "Thank you for the time today. Attached is the recovery schedule we discussed.", 9, "North Prairie ISD Gym Reroof"],
    ["luis.herrera@ntxpllc.com", "pecanvalleyconcrete.example", "Pour confirmation Friday 6:30a", "Confirming 42 CY for Friday, 6:30 start, pump on site 6:00.", 2, "Elm Fork Fire Station 3"],
    ["jalen.brooks@ntxpllc.com", "kendra.batiste@northprairieisd.example", "Re: when will the gym be usable", "Working on it, will get back to you this week.", 12, "North Prairie ISD Gym Reroof"],
    ["dana.okafor@ntxpllc.com", "ap@northprairieisd.example", "Retainage release question", "Can you confirm whether retainage is released at substantial or final completion?", 7, "North Prairie ISD Gym Reroof"],
  ].map(([user, other, subject, snippet, ago, project], i) => ({
    id: "msg-" + (9100 + i), source: "gmail", user, from: i % 3 === 1 ? other : user, to: i % 3 === 1 ? user : other,
    subject, snippet, date: iso(ago, 9 + (i % 7)), thread_id: "18f" + (2000 + i * 17).toString(16), link: "https://mail.google.com/mail/u/0/#all/18f" + (2000 + i * 17).toString(16), score: 0, project,
  }));
  const driveFiles = [
    { id: "f1", name: "2417 Pay App 04 — G702-G703.xlsx", owner: "dana.okafor@ntxpllc.com", mime: "application/vnd.google-apps.spreadsheet", modified: iso(2), link: "https://drive.google.com/file/d/f1", shared_externally: false },
    { id: "f2", name: "2417 Submittals — Roofing Package", owner: "tessa.varga@ntxpllc.com", mime: "application/vnd.google-apps.folder", modified: iso(3), link: "https://drive.google.com/drive/folders/f2", shared_externally: true },
    { id: "f3", name: "Cedar Hollow — Recovery Schedule.pdf", owner: "marcus.delgado@ntxpllc.com", mime: "application/pdf", modified: iso(5), link: "https://drive.google.com/file/d/f3", shared_externally: true },
    { id: "f4", name: "Elm Fork FS3 — Estimate Rev B.xlsx", owner: "renee.whitfield@ntxpllc.com", mime: "application/vnd.google-apps.spreadsheet", modified: iso(6), link: "https://drive.google.com/file/d/f4", shared_externally: false },
    { id: "f5", name: "Daily Reports — October", owner: "cole.ashby@ntxpllc.com", mime: "application/vnd.google-apps.folder", modified: iso(1), link: "https://drive.google.com/drive/folders/f5", shared_externally: false },
    { id: "f6", name: "NTXP W-9 2026.pdf", owner: "alison@ntxpllc.com", mime: "application/pdf", modified: iso(40), link: "https://drive.google.com/file/d/f6", shared_externally: true },
    { id: "f7", name: "RFI-014 Roof Drain Tie-in.docx", owner: "jalen.brooks@ntxpllc.com", mime: "application/vnd.google-apps.document", modified: iso(4), link: "https://drive.google.com/file/d/f7", shared_externally: false },
    { id: "f8", name: "Brazos Roofing — Subcontract 2417-07.pdf", owner: "trevor@ntxpllc.com", mime: "application/pdf", modified: iso(30), link: "https://drive.google.com/file/d/f8", shared_externally: false },
  ];

  /* ---------- Runbook ---------- */
  const runbook = [
    { id: "RB-001", workflow: "Pay application", symptom: "Pay app stuck in 'Awaiting backup' for more than 2 days", likely_cause: "A sub lien waiver or the updated G703 has not been uploaded to the job folder.",
      steps: ["Open the job's 07 Pay Applications folder and check the Backup subfolder.", "Compare the waiver list against subs billed this period.", "Email the missing sub using the 'Lien waiver request' template.", "Re-run the pay-app checker from JobTread once files land."], escalate_to: "Dana Okafor", tier: 1, updated: iso(12) },
    { id: "RB-002", workflow: "Contacts sync", symptom: "A contact labeled ★ NTXP Shared is not in the shared address book", likely_cause: "Label was applied in a secondary Google account or the nightly sync failed.",
      steps: ["Confirm the label name is exactly '★ NTXP Shared'.", "Check the source user in Admin › Shared Contacts › Workspace.", "Click 'Sync now' and wait for the pulled count.", "If still missing, check the Sync log in the Admin DB sheet."], escalate_to: "Trevor Hopkins", tier: 0, updated: iso(4) },
    { id: "RB-003", workflow: "Submittal routing", symptom: "Architect says a submittal was never received", likely_cause: "Transmittal sent from a personal mailbox, or the attachment exceeded 25 MB and bounced.",
      steps: ["Search the submittal number in Admin › Search across all mailboxes.", "Check for a bounce notice in the sender's mailbox.", "Re-send as a Drive link from the 04 Submittals folder.", "Log the re-send date in the submittal register."], escalate_to: "Marcus Delgado", tier: 1, updated: iso(20) },
    { id: "RB-004", workflow: "Signature gate", symptom: "Document waiting on signature approval will not release", likely_cause: "The file changed after approval; Tier 3 approval is bound to the exact file.",
      steps: ["Open the approval record and compare the file hash.", "If the file changed, request approval again for the new file.", "Only Alison Hopkins signs; Trevor signs only when the stated circumstance requires it."], escalate_to: "Alison Hopkins", tier: 3, updated: iso(2) },
    { id: "RB-005", workflow: "Project intake", symptom: "New job folder created without the numbered subfolders", likely_cause: "Folder created by hand instead of through the intake workflow.",
      steps: ["Run the folder audit from the intake workflow.", "Move any files into the correct numbered subfolders.", "Remove the hand-made folder once empty."], escalate_to: "Priya Natarajan", tier: 1, updated: iso(9) },
  ];

  /* ---------- Users ---------- */
  const users = staff.map((s, i) => ({ email: s.email, name: s.name, suspended: s.email === "luis.herrera@ntxpllc.com" ? false : false,
    last_login: iso(i % 4, 7 + i), is_admin: i < 2, org_unit: i < 2 ? "/Owners" : i % 3 === 0 ? "/Field" : "/Office" }));
  users.push({ email: "intern.fall@ntxpllc.com", name: "Fall Intern (unassigned)", suspended: true, last_login: iso(48, 9), is_admin: false, org_unit: "/Temporary" });
  const staged = {};
  let changeSeq = 100;

  /* ---------- Guided search ---------- */
  let lastIntent = "message";
  function guide(text) {
    const t = (text || "").toLowerCase();
    const found = staff.filter((s) => t.includes(s.name.split(" ")[0].toLowerCase()) || t.includes(s.name.split(" ")[1].toLowerCase()));
    const projects = ["North Prairie ISD Gym Reroof", "Cedar Hollow Library", "Elm Fork Fire Station 3"];
    const proj = projects.find((p) => p.toLowerCase().split(" ").some((w) => w.length > 4 && t.includes(w)));
    let intent = "message";
    if (/(trend|how often|over time|pattern|month|weekly|increase|decrease)/.test(t)) intent = "trend";
    else if (proj || /project|job/.test(t)) intent = "project";
    else if (found.length && /(about|from|with|what has|activity)/.test(t) && !/(email|message|thread)/.test(t)) intent = "person";
    const stop = new Set(["the", "a", "an", "about", "from", "with", "that", "this", "for", "and", "or", "to", "of", "in", "on", "email", "message", "find", "me", "was", "is", "what", "how", "often", "show", "i", "looking", "sent", "any", "has"]);
    const keywords = t.replace(/[^a-z0-9\- ]/g, " ").split(/\s+/).filter((w) => w.length > 2 && !stop.has(w) && !found.some((s) => s.name.toLowerCase().includes(w))).slice(0, 5);
    const restated = {
      message: `You want a specific message${found.length ? " involving " + found.map((s) => s.name).join(", ") : ""}${keywords.length ? " about " + keywords.join(", ") : ""}.`,
      trend: `You want to see how ${keywords.length ? keywords.join(" / ") : "this topic"} has changed over time${found.length ? " for " + found.map((s) => s.name).join(", ") : " across the team"}.`,
      project: `You want a picture of ${proj || "a project"} — who is involved, what is open, and the latest messages.`,
      person: `You want a summary of recent activity for ${found.map((s) => s.name).join(", ")}.`,
    }[intent];
    const questions = [
      { id: "mailboxes", question: "Which mailboxes should I search?", options: staff.map((s) => s.name), multi: true },
      { id: "window", question: "What time window?", options: ["Last 7 days", "Last 30 days", "Last 90 days", "This year"], multi: false },
      { id: "direction", question: "Messages sent, received, or both?", options: ["Received from clients", "Sent by NTXP", "Both"], multi: false },
    ];
    if (intent === "trend") questions.push({ id: "bucket", question: "Group the trend by…", options: ["Week", "Month"], multi: false });
    if (!proj) questions.push({ id: "project", question: "Is this tied to a project?", options: projects.concat(["Not sure"]), multi: false });
    lastIntent = intent;
    return {
      intent, restated, questions,
      draft: { people: found.map((s) => s.name), users: found.map((s) => s.email), from: "", to: "", date_from: isoDate(30), date_to: isoDate(0),
               keywords, project: proj || "", has_attachment: /attach|pdf|file|drawing/.test(t), labels: [] },
      jev: jev(1, 0.002),
    };
  }

  function run(body) {
    const draft = (body && body.draft) || {};
    const answers = (body && body.answers) || {};
    const scope = (body && body.scope) || "all";
    const kws = (draft.keywords || []).map((k) => String(k).toLowerCase()).filter(Boolean);
    let users = (draft.users || []).slice();
    if (Array.isArray(answers.mailboxes) && answers.mailboxes.length) {
      users = users.concat(answers.mailboxes.map((n) => (staff.find((s) => s.name === n) || {}).email).filter(Boolean));
    }
    const project = (lastIntent === "project" || lastIntent === "person" || draft.project) && draft.project ? draft.project : draft.project || (answers.project && answers.project !== "Not sure" ? answers.project : "");
    let pool = [];
    if (scope !== "drive") pool = pool.concat(messages);
    if (scope !== "gmail") pool = pool.concat(driveFiles.map((f) => ({ id: f.id, source: "drive", user: f.owner, from: f.owner, to: "", subject: f.name, snippet: f.mime.replace("application/", "").replace("vnd.google-apps.", "Google "), date: f.modified, thread_id: null, link: f.link, score: 0, project: "" })));
    const results = pool.map((m) => {
      const hay = (m.subject + " " + m.snippet + " " + m.from + " " + m.to + " " + (m.project || "")).toLowerCase();
      let s = 0.18;
      kws.forEach((k) => { if (hay.includes(k)) s += 0.5 / Math.max(1, kws.length) + 0.12; });
      if (users.length && users.includes(m.user)) s += 0.22;
      if (project && m.project === project) s += 0.25;
      if (draft.has_attachment && m.source === "drive") s += 0.1;
      return Object.assign({}, m, { score: Math.min(0.99, +s.toFixed(2)) });
    }).filter((m) => m.score > 0.3 || (!kws.length && !users.length && !project))
      .sort((a, b) => b.score - a.score).slice(0, body.limit || 25)
      .map((m) => { const r = Object.assign({}, m); delete r.project; return r; });
    const wantTrend = lastIntent === "trend" || answers.bucket;
    const trend = wantTrend ? {
      buckets: (answers.bucket === "Month" ? ["May", "Jun", "Jul", "Aug", "Sep", "Oct"] : ["Aug 17", "Aug 24", "Aug 31", "Sep 7", "Sep 14", "Sep 21", "Sep 28", "Oct 5"])
        .map((p, i, a) => ({ period: p, count: Math.round(4 + i * 1.6 + ((i * 7) % 5) + (i === a.length - 1 ? 5 : 0)) })),
      by_person: [{ person: "Jalen Brooks", count: 19 }, { person: "Cole Ashby", count: 11 }, { person: "Dana Okafor", count: 8 }, { person: "Renee Whitfield", count: 5 }, { person: "Marcus Delgado", count: 3 }],
      summary: "Volume is rising steadily, with the sharpest jump in the latest period. Most of the increase traces to the North Prairie ISD gym reroof and is concentrated in two field mailboxes.",
    } : null;
    const proj = project ? {
      name: project,
      people: Array.from(new Set(messages.filter((m) => m.project === project).map((m) => fullName(m.user)))),
      open_items: project.startsWith("North") ? ["RFI-014 roof drain tie-in — overdue", "Invoice 30551 variance $4,860", "Retainage release terms unconfirmed", "Pay app #4 backup incomplete"]
        : project.startsWith("Cedar") ? ["Submittal 23 05 00-02 resubmittal", "ASI-03 storefront pricing", "Daily report photos missing 10/05–10/09"] : ["Pour Friday 6:30a — confirm pump", "Revised estimate awaiting client approval"],
      summary: `${project} has ${messages.filter((m) => m.project === project).length} recent threads across ${new Set(messages.filter((m) => m.project === project).map((m) => m.user)).size} mailboxes. The most urgent item is listed first.`,
    } : null;
    return { results, trend, project: proj, jev: jev(trend || proj ? 2 : 1, trend || proj ? 0.031 : 0.004) };
  }

  /* ---------- Import parsing ---------- */
  function parseCSVLine(line) {
    const out = []; let cur = ""; let q = false;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (q) { if (c === '"' && line[i + 1] === '"') { cur += '"'; i++; } else if (c === '"') q = false; else cur += c; }
      else if (c === '"') q = true; else if (c === ",") { out.push(cur); cur = ""; } else cur += c;
    }
    out.push(cur); return out;
  }
  function parseImport(text, fmt) {
    const rows = [];
    let format = fmt;
    if (fmt === "auto" || !fmt) {
      if (/BEGIN:VCARD/i.test(text)) format = "vcf";
      else if (/^.*Given Name.*E-mail 1 - Value/im.test(text)) format = "google_csv";
      else if (/^.*First Name.*E-mail Address/im.test(text)) format = "outlook_csv";
      else format = "csv";
    }
    if (format === "vcf") {
      text.split(/END:VCARD/i).forEach((card) => {
        if (!/BEGIN:VCARD/i.test(card)) return;
        const get = (k) => { const m = card.match(new RegExp("^" + k + "[^:\\n]*:(.*)$", "im")); return m ? m[1].trim() : ""; };
        const all = (k) => (card.match(new RegExp("^" + k + "[^:\\n]*:(.*)$", "gim")) || []).map((l) => l.split(":").slice(1).join(":").trim());
        const n = get("N").split(";");
        rows.push({ name: get("FN") || [n[1], n[0]].filter(Boolean).join(" "), given: n[1] || "", family: n[0] || "", emails: all("EMAIL"), phones: all("TEL"), org: get("ORG").replace(/;+$/, ""), title: get("TITLE"), address: get("ADR").split(";").filter(Boolean).join(", "), notes: get("NOTE") });
      });
    } else {
      const lines = text.split(/\r?\n/).filter((l) => l.trim());
      const head = parseCSVLine(lines.shift() || "").map((h) => h.trim().toLowerCase());
      const col = (...names) => head.findIndex((h) => names.includes(h));
      const iName = col("name", "full name", "display name"), iG = col("given name", "first name", "first"), iF = col("family name", "last name", "last");
      const iE = col("e-mail 1 - value", "e-mail address", "email", "email address"), iP = col("phone 1 - value", "mobile phone", "business phone", "phone");
      const iO = col("organization 1 - name", "company", "organization", "org"), iT = col("organization 1 - title", "job title", "title"), iN = col("notes");
      lines.forEach((l) => {
        const c = parseCSVLine(l); const v = (i) => (i >= 0 ? (c[i] || "").trim() : "");
        const given = v(iG), family = v(iF);
        rows.push({ name: v(iName) || [given, family].filter(Boolean).join(" "), given, family, emails: v(iE) ? [v(iE)] : [], phones: v(iP) ? [v(iP)] : [], org: v(iO), title: v(iT), address: "", notes: v(iN) });
      });
    }
    return { format, rows: rows.filter((r) => r.name || r.emails.length) };
  }

  /* ---------- CSV export ---------- */
  function toGoogleCSV(list) {
    const head = ["Name", "Given Name", "Family Name", "E-mail 1 - Type", "E-mail 1 - Value", "Phone 1 - Type", "Phone 1 - Value", "Organization 1 - Name", "Organization 1 - Title", "Address 1 - Formatted", "Notes", "Group Membership"];
    const q = (s) => '"' + String(s == null ? "" : s).replace(/"/g, '""') + '"';
    const lines = [head.join(",")];
    list.forEach((c) => lines.push([c.name, c.given, c.family, "Work", (c.emails || []).join(" ::: "), "Work", (c.phones || []).join(" ::: "), c.org, c.title, c.address, c.notes,
      ["* myContacts"].concat(c.labels || []).join(" ::: ")].map(q).join(",")));
    return lines.join("\r\n") + "\r\n";
  }

  /* ---------- Router ---------- */
  const ok = (data) => ({ status: 200, data: clone(data) });
  const err = (status, message, code) => ({ status, data: { error: message, code: code || "error" } });

  async function handle(method, url, body) {
    const u = new URL(url, "https://admin.ntxpllc.com");
    const p = u.pathname; const q = u.searchParams;
    await new Promise((r) => setTimeout(r, 120 + Math.random() * 180));
    let m;
    if (method === "GET" && p === "/api/me") return ok(me);
    if (method === "GET" && p === "/api/health") return ok(health);
    if (method === "GET" && p === "/api/actions") return ok(actions);

    if (method === "POST" && p === "/api/search/guide") return ok(guide(body && body.text));
    if (method === "POST" && p === "/api/search/run") return ok(run(body || {}));

    if (method === "GET" && p === "/api/contacts") {
      const src = q.get("source") || "all"; const term = (q.get("q") || "").toLowerCase();
      let list = contacts.filter((c) => src === "all" || (src === "shared" ? c.shared || c.source === "shared" : c.source === src));
      if (term) list = list.filter((c) => [c.name, c.org, c.title, c.notes, c.address].concat(c.emails, c.phones, c.labels).join(" ").toLowerCase().includes(term));
      return ok({ contacts: list.slice(0, +(q.get("limit") || 500)), next_cursor: null });
    }
    if (method === "GET" && p === "/api/contacts/export") {
      const ids = (q.get("ids") || "").split(",").filter(Boolean);
      const src = q.get("source");
      const list = ids.length ? contacts.filter((c) => ids.includes(c.id)) : contacts.filter((c) => !src || src === "all" || (src === "shared" ? c.shared : c.source === src));
      return { status: 200, text: toGoogleCSV(list), type: "text/csv" };
    }
    if (method === "POST" && p === "/api/contacts/sync") {
      const added = contacts.filter((c) => (c.labels || []).includes("★ NTXP Shared") && !c.shared);
      added.forEach((c) => { c.shared = true; });
      return ok({ pulled: contacts.filter((c) => c.source === "workspace").length, shared_added: added.length, shared_removed: 0 });
    }
    if (method === "POST" && p === "/api/contacts/bulk") {
      const ids = body.ids || []; const action = body.action;
      if (action === "delete") return ok({ needs_approval: true, tier: 3, summary: `Delete ${ids.length} contact${ids.length === 1 ? "" : "s"} permanently from Google Contacts and the IPDM shared address book. This is a Tier 3 change: it is staged, not performed, until an owner approves it inside Claude, bound to this exact list.` });
      let done = 0; const failed = [];
      ids.forEach((id) => {
        const c = contacts.find((x) => x.id === id);
        if (!c) { failed.push({ id, error: "not found" }); return; }
        if (action === "share") { c.shared = true; if (!c.labels.includes("★ NTXP Shared")) c.labels.unshift("★ NTXP Shared"); }
        else if (action === "unshare") {
          if (c.source === "directory") { failed.push({ id, error: "Directory profiles are always shared" }); return; }
          c.shared = false; c.labels = c.labels.filter((l) => l !== "★ NTXP Shared");
        }
        else if (action === "label") { if (body.label && !c.labels.includes(body.label)) c.labels.push(body.label); }
        else if (action === "unlabel") { c.labels = c.labels.filter((l) => l !== body.label); }
        c.updated = new Date().toISOString(); done++;
      });
      return ok({ done, failed, tier: 1 });
    }
    if (method === "POST" && p === "/api/contacts/import") {
      const file = body && body.get ? body.get("file") : null;
      if (!file) return err(400, "No file uploaded", "no_file");
      const text = await file.text();
      const parsed = parseImport(text, q.get("format") || "auto");
      const target = q.get("target") || "shared";
      const preview = parsed.rows.map((r, i) => Object.assign({ id: "new:" + i, source: target, labels: target === "shared" ? ["★ NTXP Shared"] : [], shared: target === "shared", owner_user: me.email, updated: new Date().toISOString() }, r));
      const duplicates = [];
      preview.forEach((r) => {
        const hit = contacts.find((c) => r.emails.some((e) => c.emails.map((x) => x.toLowerCase()).includes(e.toLowerCase())) || (r.name && c.name.toLowerCase() === r.name.toLowerCase()));
        if (hit) duplicates.push({ incoming: r.name || r.emails[0], existing_id: hit.id });
      });
      let created = 0, skipped = 0;
      if (q.get("commit") === "true") {
        preview.forEach((r) => {
          if (duplicates.some((d) => d.incoming === (r.name || r.emails[0]))) { skipped++; return; }
          contacts.unshift(Object.assign({}, r, { id: (target === "shared" ? "sh:" : "ws:people/c") + (++contactSeq) })); created++;
        });
      }
      return ok({ format: parsed.format, preview, duplicates, created, skipped });
    }
    if ((m = p.match(/^\/api\/contacts\/(.+)$/)) && method === "PATCH") {
      const id = decodeURIComponent(m[1]);
      const c = contacts.find((x) => x.id === id);
      if (!c) return err(404, "Contact not found", "not_found");
      if (body && typeof body.emails !== "undefined" && (body.emails || []).some((e) => e && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(e))) return err(422, "That does not look like a valid email address", "invalid_email");
      Object.assign(c, body || {});
      if (body && "name" in body) { const parts = String(body.name).trim().split(/\s+/); c.given = parts[0] || ""; c.family = parts.slice(1).join(" "); }
      if (body && "labels" in body) c.shared = c.source === "directory" || c.labels.includes("★ NTXP Shared");
      c.updated = new Date().toISOString();
      return ok(c);
    }

    if (method === "GET" && p === "/api/analytics/summary") return ok({ updated: summaryUpdated, tiles, people });
    if ((m = p.match(/^\/api\/analytics\/report\/(.+)$/)) && method === "GET") return ok(buildReport(decodeURIComponent(m[1])));
    if (method === "POST" && p === "/api/analytics/run") {
      const t = tick(); summaryUpdated = new Date().toISOString();
      const flag = { id: "FL-2026-10-09-0" + (10 + flags.length), person: "luis.herrera@ntxpllc.com", kpi: "cross_channel_confirmation", level: 1, urgency: "low", channel: "quo", severity: "note",
        confidence: 0.61, volatility: 0.1, summary: "Two Quo calls with the concrete supplier have no matching email or JobTread confirmation.",
        evidence: [{ source: "quo", ref: "Calls 10/09 06:12, 06:40", note: "Supplier calls about pour time." }], crosscheck: { status: "pending", sources_checked: ["quo"], explanations: [] },
        council: null, created: new Date().toISOString(), status: "open", escalations: [{ level: 1, channel: "daily_note", at: new Date().toISOString(), to: ["trevor@ntxpllc.com"] }] };
      flags.unshift(flag);
      return ok({ flags_created: 1, flags_escalated: 0, jev: jev(2, 0.06), changed_tile: t.id });
    }
    if (method === "GET" && p === "/api/flags") {
      const st = q.get("status") || "open"; const lv = q.get("level");
      return ok({ flags: flags.filter((f) => (st === "all" || (st === "open" ? f.status === "open" || f.status === "ack" : f.status === st)) && (!lv || String(f.level) === lv)) });
    }
    if ((m = p.match(/^\/api\/flags\/(.+)\/action$/)) && method === "POST") {
      const f = flags.find((x) => x.id === decodeURIComponent(m[1]));
      if (!f) return err(404, "Flag not found", "not_found");
      const a = body.action;
      if (a === "ack") f.status = "ack";
      else if (a === "dismiss") f.status = "dismissed";
      else if (a === "resolve") f.status = "resolved";
      else if (a === "escalate") {
        f.level = Math.min(3, f.level + 1);
        f.escalations.push({ level: f.level, channel: f.level === 3 ? "sms" : "email", at: new Date().toISOString(), to: f.level === 3 ? ["trevor@ntxpllc.com", "alison@ntxpllc.com"] : ["trevor@ntxpllc.com"] });
      }
      if (body.note) f.crosscheck.explanations = f.crosscheck.explanations.concat(["Owner note: " + body.note]);
      return ok(f);
    }

    if (method === "GET" && p === "/api/runbook") {
      const term = (q.get("q") || "").toLowerCase();
      return ok({ entries: runbook.filter((e) => !term || JSON.stringify(e).toLowerCase().includes(term)) });
    }
    if (method === "POST" && p === "/api/runbook") {
      const e = Object.assign({ id: "RB-" + String(runbook.length + 1).padStart(3, "0"), updated: new Date().toISOString() }, body);
      runbook.unshift(e); return ok(e);
    }

    if (method === "GET" && p === "/api/users") return ok({ users });
    if ((m = p.match(/^\/api\/users\/(.+)\/action$/)) && method === "POST") {
      const email = decodeURIComponent(m[1]); const user = users.find((x) => x.email === email);
      if (!user) return err(404, "User not found", "not_found");
      const id = "CHG-" + (++changeSeq);
      const verb = { suspend: `Suspend ${user.name} (${email}). They are signed out everywhere and cannot sign in until restored.`,
        unsuspend: `Restore ${user.name} (${email}). Sign-in and mail delivery resume immediately.`,
        reset_signin: `Reset sign-in cookies for ${user.name} (${email}). All active sessions end; the password is unchanged.`,
        transfer_drive: `Transfer all Drive files owned by ${user.name} (${email}) to ${body.to || "(no target)"}. Sharing is preserved.` }[body.action];
      staged[id] = { email, action: body.action, to: body.to };
      return ok({ needs_approval: true, summary: verb || "Unknown action", change_id: id, tier: 3 });
    }
    if ((m = p.match(/^\/api\/approve\/(.+)$/)) && method === "POST") {
      const c = staged[decodeURIComponent(m[1])];
      if (!c) return err(404, "Change not found or already applied", "not_found");
      const user = users.find((x) => x.email === c.email);
      if (c.action === "suspend") user.suspended = true;
      if (c.action === "unsuspend") user.suspended = false;
      delete staged[decodeURIComponent(m[1])];
      return ok({ applied: true, change_id: m[1], action: c.action, email: c.email });
    }
    if (method === "GET" && p === "/api/drive/search") {
      const term = (q.get("q") || "").toLowerCase(); const user = q.get("user");
      return ok({ files: driveFiles.filter((f) => (!term || f.name.toLowerCase().includes(term) || (term === "external" && f.shared_externally)) && (!user || f.owner === user)) });
    }
    return err(404, "No demo handler for " + method + " " + p, "not_found");
  }

  function tick() {
    const t = tiles[Math.floor(Math.random() * tiles.length)];
    const delta = (Math.random() - 0.45) * (t.unit === "%" ? 3 : t.unit === "h" ? 0.6 : t.unit === "/100" ? 3 : 1.4);
    let v = t.value + delta;
    if (t.unit === "%") v = Math.max(50, Math.min(100, v));
    v = t.unit === "h" ? +v.toFixed(1) : t.unit === "%" || t.unit === "/100" ? Math.round(v) : Math.max(0, Math.round(v));
    t.trend = +(v - t.value + t.trend * 0.5).toFixed(1);
    t.value = v; t.display = String(v);
    if (t.kind === "pie" || (t.kind === "bar" && t.unit !== "%")) {
      const sum = t.breakdown.reduce((a, b) => a + b.value, 0);
      const diff = v - sum;
      if (diff) t.breakdown[0].value = Math.max(0, t.breakdown[0].value + diff);
    }
    summaryUpdated = new Date().toISOString();
    return clone(t);
  }

  window.NTXPDemo = { handle, tick };
})();
