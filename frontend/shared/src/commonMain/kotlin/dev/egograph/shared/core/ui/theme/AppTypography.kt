package dev.egograph.shared.core.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.runtime.Composable
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

val Typography.monospaceBodyMedium: TextStyle
    @Composable
    @ReadOnlyComposable
    get() =
        bodyMedium.copy(
            fontFamily = FontFamily.Monospace,
            fontWeight = FontWeight.Medium,
        )

val Typography.monospaceBody: TextStyle
    @Composable
    @ReadOnlyComposable
    get() = bodyMedium.copy(fontFamily = FontFamily.Monospace)

val Typography.monospaceLabelSmall: TextStyle
    @Composable
    @ReadOnlyComposable
    get() =
        labelSmall.copy(
            fontFamily = FontFamily.Monospace,
            letterSpacing = 0.5.sp,
        )
