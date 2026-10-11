import 'package:flutter/material.dart';

/// ETHIO design tokens. Everything is drawn in code (no downloaded fonts or
/// images) so the app stays fast on slow connections.
class EthioColors {
  static const primary = Color(0xFF0B6B4F);
  static const primaryDark = Color(0xFF07452F);
  static const primarySoft = Color(0xFFE2F1EA);
  static const accent = Color(0xFFF2A93B);
  static const accentSoft = Color(0xFFFFF1D6);
  static const ink = Color(0xFF122019);
  static const muted = Color(0xFF5C6C64);
  static const line = Color(0xFFE1E8E4);
  static const bg = Color(0xFFF5F8F6);
  static const card = Colors.white;
  static const danger = Color(0xFFB3261E);
  static const dangerSoft = Color(0xFFFBE9E7);
  static const ok = Color(0xFF1B7A43);
  static const okSoft = Color(0xFFE2F3E8);
  static const warn = Color(0xFF8A5A00);
  static const warnSoft = Color(0xFFFFF3D4);
  static const info = Color(0xFF0B5CAD);
  static const infoSoft = Color(0xFFE2EFFD);

  // Translucent helpers as explicit ARGB values (no withOpacity needed).
  static const primary12 = Color(0x1F0B6B4F);
  static const ink12 = Color(0x1F122019);
  static const white70 = Color(0xB3FFFFFF);
}

class EthioTheme {
  static ThemeData light() {
    final scheme = ColorScheme.fromSeed(
      seedColor: EthioColors.primary,
      primary: EthioColors.primary,
      secondary: EthioColors.accent,
      surface: Colors.white,
    );
    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      scaffoldBackgroundColor: EthioColors.bg,
      appBarTheme: const AppBarTheme(
        backgroundColor: Colors.white,
        foregroundColor: EthioColors.ink,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(
          fontSize: 20,
          fontWeight: FontWeight.w800,
          color: EthioColors.ink,
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: EthioColors.primary,
          foregroundColor: Colors.white,
          minimumSize: const Size(0, 58),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
          textStyle: const TextStyle(
            fontSize: 17,
            fontWeight: FontWeight.w700,
          ),
          elevation: 0,
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size(0, 58),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
          side: const BorderSide(color: EthioColors.primary, width: 1.6),
          textStyle: const TextStyle(
            fontSize: 17,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          minimumSize: const Size(0, 48),
          textStyle: const TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: Colors.white,
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 18, vertical: 18),
        hintStyle: const TextStyle(color: EthioColors.muted, fontSize: 16),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: EthioColors.line),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: EthioColors.line),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide:
              const BorderSide(color: EthioColors.primary, width: 2),
        ),
      ),
      dividerTheme: const DividerThemeData(color: EthioColors.line),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
        ),
      ),
    );
  }
}

/// Shared text styles so type stays consistent without a font download.
class EthioText {
  static const h1 = TextStyle(
      fontSize: 28, fontWeight: FontWeight.w800, color: EthioColors.ink);
  static const h2 = TextStyle(
      fontSize: 22, fontWeight: FontWeight.w800, color: EthioColors.ink);
  static const h3 = TextStyle(
      fontSize: 18, fontWeight: FontWeight.w700, color: EthioColors.ink);
  static const body =
      TextStyle(fontSize: 16, color: EthioColors.ink, height: 1.45);
  static const bodyMuted =
      TextStyle(fontSize: 16, color: EthioColors.muted, height: 1.45);
  static const small =
      TextStyle(fontSize: 14, color: EthioColors.muted, height: 1.4);
  static const smallBold =
      TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: EthioColors.ink);
  static const caption =
      TextStyle(fontSize: 13, color: EthioColors.muted, height: 1.4);
}
