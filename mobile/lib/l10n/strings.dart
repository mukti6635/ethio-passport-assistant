import 'package:flutter/widgets.dart';

/// ETHIO localization.
///
/// English is complete. Amharic ('am') covers ~100 core keys (chrome,
/// home, services, intake, stages, documents, review, issues, approvals,
/// OTP/CAPTCHA/payment/legal, appointments, history, common actions,
/// privacy notices); Afaan Oromo ('om') is registered but empty.
/// Every lookup falls back to English per key, so untranslated keys never
/// break the UI. The home screen shows 'am' as supported and 'om' as
/// coming soon.
class S {
  S(this.locale);

  final Locale locale;

  static S of(BuildContext context) {
    final s = Localizations.of<S>(context, S);
    assert(s != null, 'EthioLocalizationsDelegate is missing');
    return s!;
  }

  /// Translate [key], optionally filling `{name}` placeholders in [params].
  String t(String key, [Map<String, String>? params]) {
    var value = localized[locale.languageCode]?[key] ?? _en[key] ?? key;
    if (params != null) {
      params.forEach((k, v) => value = value.replaceAll('{$k}', v));
    }
    return value;
  }

  static const Map<String, Map<String, String>> localized = {
    'en': _en,
    // TODO(i18n): add Amharic translations here.
    'am': <String, String>{
  // App chrome
  'app_tagline': 'የእርስዎ የኢትዮጵያ መንግሥት አገልግሎት ረዳት',
  'not_affiliated':
      'ገለልተኛ ረዳት። ከማንኛውም የመንግሥት ተቋም ጋር የተገናኘ አይደለም።',
  'prototype_banner':
      'ፕሮቶታይፕ — የማሳያ መረጃ ብቻ። ምንም ወደ መንግሥት አይላክም።',
  'tab_home': 'መነሻ',
  'tab_tasks': 'የእኔ ተግባራት',
  'tab_history': 'ታሪክ',

  // Home
  'home_heading': 'በምን ልረዳዎት?',
  'home_sub': 'ETHIO የሚፈልጉትን ይንገሩት እና እርምጃ በርምጃ ይመራዎታል።',
  'describe_hint': 'የሚፈልጉትን እርዳታ ይግለጹ...',
  'start_button': 'ጀምር',
  'services_title': 'አገልግሎቶች',
  'language': 'ቋንቋ',

  // Services
  'svc_passport': 'ፓስፖርት',
  'svc_passport_desc': 'አዲስ፣ እድሳት ወይም ምትክ',
  'svc_visa': 'ቪዛ',
  'svc_visa_desc': 'የጉዞ ቪዛዎች እና ፈቃዶች',
  'svc_license': 'የመንጃ ፈቃድ',
  'svc_license_desc': 'አዲስ ወይም የታደሰ የመንጃ ፈቃድ',
  'svc_certificates': 'ሰርተፊኬቶች',
  'svc_certificates_desc': 'የልደት፣ የጋብቻ እና ሌሎች',
  'svc_business': 'የንግድ አገልግሎቶች',
  'svc_business_desc': 'ፈቃዶች እና ምዝገባዎች',
  'svc_other': 'ሌሎች የመንግሥት አገልግሎቶች',
  'svc_other_desc': 'ሊረዳዎት የሚችል ማንኛውም ነገር',

  // Intake
  'intake_title': 'እንጀምር',
  'intake_step': 'እርምጃ {n} ከ {total}',
  'intake_continue': 'ቀጥል',
  'intake_back': 'ተመለስ',
  'intake_finish': 'ተግባሬን ፍጠር',
  'intake_review': 'መልስዎችዎን ይመልከቱ',
  'intake_edit': 'መልስ ለመቀየር በቀደሙት ማያ ገጾች ላይ ይንኩ።',

  // Overview
  'ov_next': 'ቀጣይ እርምጃ',
  'ov_progress': 'ሂደት',
  'ov_open': 'ክፈት',
  'ov_created': 'የተፈጠረው {date}',
  'next_requirements': 'የሚያስፈልጉ ሰነዶችዎን ይመልከቱ',
  'next_documents': 'ሰነዶችዎን ይስቀሉ',
  'next_review': 'መረጃዎን ይመልከቱ',
  'next_issues': '{n} ክፍት ነገሮችን ያስተካክሉ',
  'next_approvals': '{n} ማጽደቆችን ያጠናቅቁ',
  'next_appointment': 'ቀጠሮዎን ይያዙ',
  'next_done': 'ሁሉም ተጠናቋል',

  // Stages
  'stage_intake': 'መግቢያ',
  'stage_requirements': 'መስፈርቶች',
  'stage_documents': 'ሰነዶች',
  'stage_review': 'ግምገማ',
  'stage_issues': 'ችግሮችን ማስተካከል',
  'stage_approvals': 'ማጽደቆች',
  'stage_appointment': 'ቀጠሮ',
  'stage_done': 'ተጠናቋል',

  // Requirements
  'req_sub': 'ሰነዱን ለማከል መስፈርት ይንኩ።',
  'req_ready': 'ዝግጁ',
  'req_missing': 'ጎድሏል',

  // Upload
  'up_title': 'ሰነዶች',
  'up_add': 'ሰነድ ጨምር',
  'up_empty': 'ገና ምንም ሰነድ አልተጨመረም።',
  'up_continue': 'ወደ ግምገማ ቀጥል',
  'up_sample_note':
      'ፕሮቶታይፕ፡ ሰነዶቹ በመሣሪያዎ ላይ የማሳያ ናሙናዎች ናቸው። እውነተኛ የመታወቂያ ሰነዶችን አያክሉ።',

  // Review
  'rev_title': 'መረጃዎን ያረጋግጡ',
  'rev_sub': 'ETHIO እነዚህን ዝርዝሮች ከሰነዶችዎ አንብቧል። ስህተት ያለበትን ያስተካክሉ።',
  'rev_confirm': 'አረጋግጥ እና ቀጥል',

  // Issues
  'iss_title': 'ትኩረት ይፈልጋል',
  'iss_sub': 'ETHIO እንዲቀጥል እያንዳንዱን ንጥል ይፍቱ።',
  'iss_missing': 'የጎደለ መረጃ',
  'iss_conflict': 'የሚጋጭ መረጃ',
  'iss_resolve': 'ፍታ',
  'iss_all_done': 'ሁሉም ንጥሎች ተፈትተዋል። መቀጠል ይችላሉ።',

  // AI activity
  'ai_title': 'የ AI እንቅስቃሴ',
  'ai_sub': 'ETHIO በተግባርዎ ላይ እየሰራ ነው። የአሳሽ አውቶሜሽን በኋላ እዚህ ይገናኛል።',
  'ai_not_connected':
      'የአሳሽ አውቶሜሽን ገና አልተገናኘም — ከታች ያሉት እርምጃዎች የማሳያ ቅድመ እይታ ናቸው።',

  // Approvals
  'ap_title': 'የሚያስፈልጉ ማጽደቆች',
  'ap_sub': 'አንዳንድ እርምጃዎች እርስዎን ይፈልጋሉ፣ AIውን አይደለም። ያለእርስዎ ፈቃድ ምንም ወደፊት አይሄድም።',
  'ap_pending': 'እርስዎን በመጠባበቅ ላይ',
  'ap_approved': 'ጸድቋል',
  'ap_hint':
      'በቀጥታ መተግበሪያ ውስጥ፣ እነዚህ ማያ ገጾች ከእውነተኛ ማረጋገጫ፣ ክፍያ እና ማስገቢያ ስርዓቶች ጋር ይገናኛሉ። ይህ ፕሮቶታይፕ ያስመስላቸዋል።',

  // OTP
  'otp_title': 'የማረጋገጫ ኮድ',
  'otp_body':
      'ወደ ስልክዎ የላክነውን ባለ 6-አሃዝ ኮድ ያስገቡ። (ፕሮቶታይፕ: ማንኛውም 6 አሃዞች ይሰራሉ።)',
  'otp_resend': 'ኮድ እንደገና ላክ',
  'otp_verify': 'አረጋግጥ',
  'otp_error': 'እባክዎ ሁሉንም 6 አሃዞች ያስገቡ።',

  // CAPTCHA
  'captcha_title': 'የደህንነት ምርመራ',
  'captcha_body': 'የ{target} ምስል ያላቸውን ሁሉንም ንጣፎች ይንኩ፣ ከዚያ ያረጋግጡ።',
  'captcha_verify': 'አረጋግጥ',
  'captcha_error': 'ትክክል አይደለም — የ{target} ንጣፎችን ብቻ በመምረጥ እንደገና ይሞክሩ።',

  // Payment
  'pay_title': 'ክፍያ',
  'pay_body': 'የዚህ ተግባር የአገልግሎት ክፍያ።',
  'pay_telebirr': 'ቴሌብር',
  'pay_chapa': 'ቻፓ',
  'pay_card': 'የባንክ ካርድ',
  'pay_now': '{amount} ክፈል',
  'pay_processing': 'ክፍያ እየተሰራ ነው...',
  'pay_success': 'ክፍያ ተሳክቷል',
  'pay_demo': 'የማሳያ ክፍያ — እውነተኛ ገንዘብ አይንቀሳቀስም።',

  // Legal
  'legal_title': 'የመጨረሻ ግምገማ',
  'legal_body': 'ከታች ያለውን ማጠቃለያ በጥንቃቄ ያንብቡ። ይህ ከማስገባት በፊት የመጨረሻው እርምጃ ነው።',
  'legal_locked':
      'የፕሮቶታይፕ ሁነታ: ማስገቢያ ተሰናክሏል። በቀጥታ መተግበሪያ ውስጥ፣ ይህ አዝራር ማመልከቻዎን ወደ መንግሥት ስርዓት ይልካል።',
  'legal_submit': 'ማመልከቻ አስገባ',
  'legal_finish': 'ግምገማ አስቀምጥ እና ጨርስ',
  'legal_check_all': 'እባክዎ ለመቀጠል ሦስቱንም ሳጥኖች ምልክት ያድርጉ።',

  // Appointment
  'apt_title': 'ቀጠሮ ይያዙ',
  'apt_office': 'ቢሮ',
  'apt_day': 'ቀን ይምረጡ',
  'apt_time': 'ሰዓት ይምረጡ',
  'apt_confirm': 'ቀጠሮ አረጋግጥ',
  'apt_confirmed': 'ቀጠሮ ተያዟል',

  // History / tasks
  'hist_resume': 'ቀጥል',
  'hist_empty': 'ገና ያለፉ ተግባራት የሉም።',
  'tasks_empty': 'ንቁ ተግባራት የሉም። ከመነሻ ይጀምሩ።',
  'status_in_progress': 'በሂደት ላይ',
  'status_complete': 'ተጠናቋል',

  // Common actions
  'common_cancel': 'ሰርዝ',
  'common_close': 'ዝጋ',
  'common_save': 'አስቀምጥ',
  'common_continue': 'ቀጥል',
  'common_back': 'ተመለስ',
  'common_done': 'ተጠናቋል',

  // Privacy notices
  'privacy_title': 'መረጃዎ የእርስዎ ነው',
  'privacy_upload':
      'ይህ ፕሮቶታይፕ እዚህ የሚያክሏቸውን የናሙና ፋይሎች ብቻ ይጠቀማል። ሁሉም በመሣሪያዎ ላይ ይቆያል — ምንም አይሰቀልም፣ አይላክም፣ ወይም ለማንም የመንግሥት ቢሮ አይቀርብም።',
  'privacy_payment':
      'ይህ የማሳያ ክፍያ ነው፡ እውነተኛ ገንዘብ አይንቀሳቀስም፣ እና ምንም የካርድ ወይም የሂሳብ ዝርዝሮች አይሰበሰቡም፣ አይላኩም፣ ወይም አይቀመጡም።',
  'privacy_legal':
      'ይህ የመጨረሻ ግምገማ የፕሮቶታይፕ ማስመሰያ ነው። እዚህ ያረጋገጡት ምንም ወደ መንግሥት አልቀረበም፣ እና ምንም መረጃ ከዚህ መሣሪያ አይወጣም።',
  'privacy_ack': 'ተረድቻለሁ',
  'privacy_acknowledged': 'ተረድቷል',

  // AI activity states
  'ai_continue': 'ቀጥል',
  'ai_done': 'ተጠናቋል',
  'ai_running': 'እየሰራ ነው...',
  'ai_wait_msg': 'ከመቀጠልዎ በፊት AI እስኪጨርስ ይጠብቁ።',
  'ai_waiting': 'በመጠባበቅ ላይ',
  'ap_open': 'ክፈት',

  // Appointment details
  'apt_ref': 'የማሳያ ማጣቀሻ',
  'apt_ref_note': 'የማሳያ ማጣቀሻ ብቻ — እውነተኛ ቀጠሮ አይደለም።',
  'apt_summary': 'ቀጠሮዎ',

  // CAPTCHA extras
  'captcha_target': 'ብስክሌት',
  'captcha_robot': 'እኔ ሮቦት አይደለሁም',

  // Issue resolution
  'iss_continue': 'ቀጥል',
  'iss_resolved': 'ተፈትቷል',
  'iss_save': 'መልስ አስቀምጥ',
  'iss_type_fix': 'ትክክለኛውን እሴት ይተይቡ',
  'iss_use_value': 'ይህን እሴት ተጠቀም',

  // Language
  'lang_soon': 'በቅርቡ ይመጣል',
  'lang_soon_msg': '{lang} በቅርቡ ይመጣል። መተግበሪያው ለዚህ ዝግጁ ሆኖ ተገንብቷል።',

  // Legal checkboxes
  'legal_c1': 'ከላይ ያለው መረጃዬ ትክክል ነው።',
  'legal_c2': 'ይህ ፕሮቶታይፕ መሆኑን እና ምንም እንደማይላክ ተረድቻለሁ።',
  'legal_c3': 'ለማመልከቻዬ ትክክለኛነት ኃላፊነት እወስዳለሁ።',

  // Misc
  'otp_resend_in': 'በ {s} ሰከንድ እንደገና ላክ',
  'pay_method': 'የክፍያ ዘዴ',
  'pay_receipt': 'ደረሰኝ',
  'req_title': 'የሚያስፈልግዎት',
  'req_types': 'ይቀበላል: {types}',
  'rev_auto': 'ከሰነዶችዎ በራስ-ሰር የተነበበ',
  'rev_confidence': 'እርግጠኛነት',
  'rev_edit': 'አርም',
  'rev_edited': 'በእርስዎ የተስተካከለ',
  'rev_save': 'አስቀምጥ',
  'tasks_active': 'ንቁ ተግባራት',
  'up_choose_camera': 'ፎቶ አንሳ',
  'up_choose_camera_sub': 'በዚህ ፕሮቶታይፕ ተሰናክሏል',
  'up_choose_files': 'ከፋይሎች ምረጥ',
  'up_choose_files_sub': 'በዚህ ፕሮቶታይፕ ተሰናክሏል',
  'up_choose_sample': 'የናሙና ሰነድ ተጠቀም',
  'up_choose_sample_sub': 'የፕሮቶታይፕ ምትክ ፋይል',
  'up_choose_title': 'ሰነድ ጨምር',
  'up_remove': 'አስወግድ',
  'up_remove_body': 'ይህ "{name}" ከተግባርዎ ያስወግዳል። በኋላ እንደገና ማከል ይችላሉ።',
  'up_remove_title': 'ሰነድ ማስወገድ?',
  'up_sample': 'ናሙና',

  // Catalog: intake questions
  'q_purpose': 'ምን ይፈልጋሉ?',
  'q_full_name': 'ሙሉ ስም (እንደ መታወቂያዎ)',
  'q_dob': 'የልደት ቀን',
  'q_phone': 'ስልክ ቁጥር',
  'q_destination': 'መድረሻ ሀገር',
  'q_travel_date': 'የታቀደ የጉዞ ቀን',
  'q_license_class': 'የፈቃድ ክፍል',
  'q_cert_type': 'የሰርተፊኬት አይነት',
  'q_business_type': 'የንግድ አይነት',
  'q_business_name': 'የንግድ ስም',
  'q_describe': 'የሚፈልጉትን ይግለጹ',
  // Catalog: choice options
  'opt_new_passport': 'አዲስ ፓስፖርት',
  'opt_renewal': 'እድሳት',
  'opt_replacement': 'ምትክ',
  'opt_tourist': 'ቱሪስት',
  'opt_business': 'ንግድ',
  'opt_student': 'ተማሪ',
  'opt_transit': 'ትራንዚት',
  'opt_new_license': 'አዲስ ፈቃድ',
  'opt_class_a': 'ክፍል A (ሞተርሳይክል)',
  'opt_class_b': 'ክፍል B (መኪና)',
  'opt_class_c': 'ክፍል C (ጭነት መኪና)',
  'opt_birth_cert': 'የልደት ሰርተፊኬት',
  'opt_marriage_cert': 'የጋብቻ ሰርተፊኬት',
  'opt_education': 'ትምህርት',
  'opt_sole_prop': 'የግል ንግድ',
  'opt_plc': 'ኃ.የተ.የግ.ማ (PLC)',
  'opt_cooperative': 'ኅብረት ሥራ ማኅበር',
  // Catalog: requirements
  'r_national_id': 'ብሔራዊ መታወቂያ / የቀበሌ መታወቂያ',
  'r_national_id_d': 'የመታወቂያ ካርድዎ የፊት እና የኋላ ገጽ',
  'r_photo': 'የፓስፖርት መጠን ፎቶ',
  'r_photo_d': 'የቅርብ ጊዜ ፎቶ፣ ግልጽ ዳራ',
  'r_old_passport': 'የድሮ ፓስፖርት',
  'r_old_passport_d': 'ለእድሳት ብቻ',
  'r_birth_cert': 'የልደት ሰርተፊኬት',
  'r_birth_cert_d': 'ለመጀመሪያ ማመልከቻ',
  'r_passport_copy': 'የፓስፖርት ቅጂ',
  'r_passport_copy_d': 'የፓስፖርትዎ የባዮ-መረጃ ገጽ',
  'r_invitation': 'የጥሪ ደብዳቤ',
  'r_invitation_d': 'ከአስተናጋጅዎ ወይም ከአዘጋጅዎ',
  'r_medical': 'የሕክምና ሰርተፊኬት',
  'r_medical_d': 'ከተፈቀደ የጤና ማዕከል',
  'r_support': 'ደጋፊ ሰነድ',
  'r_support_d': 'ጥያቄዎን የሚያረጋግጥ ማንኛውም ሰነድ',
  'r_lease': 'የኪራይ ውል',
  'r_lease_d': 'ለንግድ ቦታዎ',
  'r_premises_photos': 'የቦታ ፎቶዎች',
  'r_premises_photos_d': 'የውጭ እና የውስጥ ፎቶዎች',
  // Catalog: AI steps
  'ai_step_check': 'መስፈርቶቹን በመፈተሽ ላይ',
  'ai_step_verify': 'ሰነዶችዎን በማረጋገጥ ላይ',
  'ai_step_draft': 'ማመልከቻዎን በማዘጋጀት ላይ',
  'ai_step_prepare': 'ሁሉንም ለግምገማ በማዘጋጀት ላይ',
    },
    // TODO(i18n): add Afaan Oromo translations here.
    'om': <String, String>{},
  };

  static const Map<String, String> _en = {
    // App chrome
    'app_tagline': 'Your Ethiopian Government Assistant',
    'not_affiliated':
        'Independent assistant. Not affiliated with any government agency.',
    'prototype_banner':
        'Prototype — demo data only. Nothing is submitted to any government.',
    'tab_home': 'Home',
    'tab_tasks': 'My Tasks',
    'tab_history': 'History',

    // Home
    'home_heading': 'What do you need help with?',
    'home_sub':
        'Tell ETHIO what you need and it will guide you, step by step.',
    'describe_hint': 'Describe what you need help with...',
    'start_button': 'Start',
    'services_title': 'Services',
    'language': 'Language',
    'lang_en': 'English',
    'lang_am': 'አማርኛ',
    'lang_om': 'Afaan Oromoo',
    'lang_soon': 'coming soon',
    'lang_soon_msg':
        '{lang} is coming soon. The app is built ready for it.',

    // Services
    'svc_passport': 'Passport',
    'svc_passport_desc': 'New, renewal or replacement',
    'svc_visa': 'Visa',
    'svc_visa_desc': 'Travel visas and permits',
    'svc_license': "Driver's License",
    'svc_license_desc': 'New or renewed driving license',
    'svc_certificates': 'Certificates',
    'svc_certificates_desc': 'Birth, marriage and more',
    'svc_business': 'Business Services',
    'svc_business_desc': 'Licenses and registrations',
    'svc_other': 'Other Government Services',
    'svc_other_desc': 'Anything else we can help with',

    // Generic intake
    'intake_title': "Let's get started",
    'intake_step': 'Step {n} of {total}',
    'intake_continue': 'Continue',
    'intake_back': 'Back',
    'intake_finish': 'Create my task',
    'intake_review': 'Review your answers',
    'intake_edit': 'Tap an answer to change it on the previous screens.',

    // Task overview
    'ov_next': 'Next step',
    'ov_progress': 'Progress',
    'ov_open': 'Open',
    'ov_created': 'Created {date}',
    'next_requirements': 'See what documents you need',
    'next_documents': 'Upload your documents',
    'next_review': 'Review your information',
    'next_issues': 'Fix {n} open items',
    'next_approvals': 'Complete {n} approvals',
    'next_appointment': 'Book your appointment',
    'next_done': 'Everything is complete',

    // Stages
    'stage_intake': 'Intake',
    'stage_requirements': 'Requirements',
    'stage_documents': 'Documents',
    'stage_review': 'Review',
    'stage_issues': 'Fix issues',
    'stage_approvals': 'Approvals',
    'stage_appointment': 'Appointment',
    'stage_done': 'Done',

    // Requirements
    'req_title': "What you'll need",
    'req_sub': 'Tap a requirement to add its document.',
    'req_ready': 'Ready',
    'req_missing': 'Missing',
    'req_types': 'Accepts: {types}',

    // Upload
    'up_title': 'Documents',
    'up_add': 'Add document',
    'up_remove': 'Remove',
    'up_remove_title': 'Remove document?',
    'up_remove_body':
        'This will remove "{name}" from your task. You can add it again later.',
    'up_sample_note':
        'Prototype: documents are simulated samples on this device. Do not add real identity documents.',
    'up_choose_title': 'Add a document',
    'up_choose_sample': 'Use a sample document',
    'up_choose_sample_sub': 'Prototype placeholder file',
    'up_choose_camera': 'Take a photo',
    'up_choose_camera_sub': 'Disabled in this prototype',
    'up_choose_files': 'Choose from files',
    'up_choose_files_sub': 'Disabled in this prototype',
    'up_empty': 'No documents added yet.',
    'up_continue': 'Continue to review',
    'up_sample': 'Sample',

    // Review extracted info
    'rev_title': 'Check your information',
    'rev_sub':
        'ETHIO read these details from your documents. Correct anything that is wrong.',
    'rev_confidence': 'Confidence',
    'rev_edit': 'Edit',
    'rev_save': 'Save',
    'rev_edited': 'Edited by you',
    'rev_confirm': 'Confirm and continue',
    'rev_auto': 'Read automatically from your documents',

    // Missing info / conflicts
    'iss_title': 'Needs your attention',
    'iss_sub': 'Resolve each item so ETHIO can continue.',
    'iss_missing': 'Missing information',
    'iss_conflict': 'Conflicting data',
    'iss_resolve': 'Resolve',
    'iss_resolved': 'Resolved',
    'iss_use_value': 'Use this value',
    'iss_type_fix': 'Type the correct value',
    'iss_save': 'Save answer',
    'iss_continue': 'Continue',
    'iss_all_done': 'All items resolved. You can continue.',

    // AI activity
    'ai_title': 'AI activity',
    'ai_sub':
        'ETHIO is working on your task. Browser automation will plug in here later.',
    'ai_not_connected':
        'Browser automation is not connected yet — the steps below are a simulated preview.',
    'ai_running': 'Working...',
    'ai_done': 'Done',
    'ai_waiting': 'Waiting',
    'ai_continue': 'Continue',
    'ai_wait_msg': 'Wait for the AI to finish before continuing.',

    // Approvals
    'ap_title': 'Approvals needed',
    'ap_sub':
        'Some steps need you, not the AI. Nothing moves forward without your approval.',
    'ap_pending': 'Waiting for you',
    'ap_approved': 'Approved',
    'ap_open': 'Open',
    'ap_hint':
        'In the live app, these screens connect to real verification, payment and submission systems. This prototype simulates them.',

    // OTP
    'otp_title': 'Verification code',
    'otp_body':
        'Enter the 6-digit code we sent to your phone. (Prototype: any 6 digits work.)',
    'otp_resend': 'Resend code',
    'otp_resend_in': 'Resend in {s}s',
    'otp_verify': 'Verify',
    'otp_error': 'Please enter all 6 digits.',

    // CAPTCHA
    'captcha_title': 'Security check',
    'captcha_body': 'Tap all tiles that show a {target}, then verify.',
    'captcha_target': 'bicycle',
    'captcha_verify': 'Verify',
    'captcha_robot': "I'm not a robot",
    'captcha_error': 'Not quite — try selecting only the {target} tiles.',

    // Payment
    'pay_title': 'Payment',
    'pay_body': 'Service fee for this task.',
    'pay_method': 'Payment method',
    'pay_telebirr': 'Telebirr',
    'pay_chapa': 'Chapa',
    'pay_card': 'Bank card',
    'pay_now': 'Pay {amount}',
    'pay_processing': 'Processing payment...',
    'pay_success': 'Payment successful',
    'pay_demo': 'Demo payment — no real money moves.',
    'pay_receipt': 'Receipt',

    // Final legal
    'legal_title': 'Final review',
    'legal_body':
        'Read the summary below carefully. This is the last step before submission.',
    'legal_c1': 'My information above is correct.',
    'legal_c2': 'I understand this is a prototype and nothing is submitted.',
    'legal_c3': 'I take responsibility for the accuracy of my application.',
    'legal_locked':
        'Prototype mode: submission is disabled. In the live app, this button would submit your application to the government system.',
    'legal_submit': 'Submit application',
    'legal_finish': 'Save review and finish',
    'legal_check_all': 'Please tick all three boxes to continue.',

    // Appointments
    'apt_title': 'Book an appointment',
    'apt_office': 'Office',
    'apt_day': 'Pick a day',
    'apt_time': 'Pick a time',
    'apt_confirm': 'Confirm appointment',
    'apt_confirmed': 'Appointment confirmed',
    'apt_ref': 'Demo reference',
    'apt_ref_note': 'Demo reference only — not a real booking.',
    'apt_summary': 'Your appointment',

    // History / tasks
    'hist_resume': 'Resume',
    'hist_empty': 'No past tasks yet.',
    'tasks_empty': 'No active tasks. Start one from Home.',
    'tasks_active': 'Active tasks',
    'status_in_progress': 'In progress',
    'status_complete': 'Complete',

    // Privacy notices
    'privacy_title': 'Your information stays yours',
    'privacy_upload':
        'This prototype only uses sample files you add here. Everything stays on this device — nothing is uploaded, sent, or submitted to any government office.',
    'privacy_payment':
        'This is a demo payment: no real money moves, and no card or account details are collected, sent, or stored anywhere.',
    'privacy_legal':
        'This final review is a prototype simulation. Nothing you confirmed here is submitted to any government, and no data leaves this device.',
    'privacy_ack': 'I understand',
    'privacy_acknowledged': 'Understood',

    // Common
    'common_cancel': 'Cancel',
    'common_close': 'Close',
    'common_save': 'Save',
    'common_continue': 'Continue',
    'common_back': 'Back',
    'common_done': 'Done',

    // Catalog: intake questions
    'q_purpose': 'What do you need?',
    'q_full_name': 'Full name (as on your ID)',
    'q_dob': 'Date of birth',
    'q_phone': 'Phone number',
    'q_destination': 'Destination country',
    'q_travel_date': 'Planned travel date',
    'q_license_class': 'License class',
    'q_cert_type': 'Certificate type',
    'q_business_type': 'Business type',
    'q_business_name': 'Business name',
    'q_describe': 'Describe what you need',
    // Catalog: choice options
    'opt_new_passport': 'New passport',
    'opt_renewal': 'Renewal',
    'opt_replacement': 'Replacement',
    'opt_tourist': 'Tourist',
    'opt_business': 'Business',
    'opt_student': 'Student',
    'opt_transit': 'Transit',
    'opt_new_license': 'New license',
    'opt_class_a': 'Class A (motorcycle)',
    'opt_class_b': 'Class B (car)',
    'opt_class_c': 'Class C (truck)',
    'opt_birth_cert': 'Birth certificate',
    'opt_marriage_cert': 'Marriage certificate',
    'opt_education': 'Education',
    'opt_sole_prop': 'Sole proprietorship',
    'opt_plc': 'PLC',
    'opt_cooperative': 'Cooperative',
    // Catalog: requirements
    'r_national_id': 'National ID / Kebele ID',
    'r_national_id_d': 'Front and back of your ID card',
    'r_photo': 'Passport-size photo',
    'r_photo_d': 'Recent photo, plain background',
    'r_old_passport': 'Old passport',
    'r_old_passport_d': 'Only for renewals',
    'r_birth_cert': 'Birth certificate',
    'r_birth_cert_d': 'For first-time applications',
    'r_passport_copy': 'Passport copy',
    'r_passport_copy_d': 'Bio-data page of your passport',
    'r_invitation': 'Invitation letter',
    'r_invitation_d': 'From your host or organizer',
    'r_medical': 'Medical certificate',
    'r_medical_d': 'From an approved health center',
    'r_support': 'Supporting document',
    'r_support_d': 'Any document that proves your request',
    'r_lease': 'Lease agreement',
    'r_lease_d': 'For your business premises',
    'r_premises_photos': 'Premises photos',
    'r_premises_photos_d': 'Exterior and interior photos',
    // Catalog: AI steps
    'ai_step_check': 'Checking the requirements',
    'ai_step_verify': 'Verifying your documents',
    'ai_step_draft': 'Drafting your application',
    'ai_step_prepare': 'Preparing everything for review',
  };
}

/// Localization delegate for [S]. English ships now; 'am' and 'om' are
/// registered so adding translations is a data-only change.
class EthioLocalizationsDelegate extends LocalizationsDelegate<S> {
  const EthioLocalizationsDelegate();

  @override
  bool isSupported(Locale locale) =>
      ['en', 'am', 'om'].contains(locale.languageCode);

  @override
  Future<S> load(Locale locale) async => S(locale);

  @override
  bool shouldReload(EthioLocalizationsDelegate old) => false;
}
