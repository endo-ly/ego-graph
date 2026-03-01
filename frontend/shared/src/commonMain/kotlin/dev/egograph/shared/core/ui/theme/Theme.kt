package dev.egograph.shared.core.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.graphics.Color

// Zinc / Slate Palette
val Zinc50 = Color(0xFFFAFAFA)
val Zinc100 = Color(0xFFF4F4F5)
val Zinc200 = Color(0xFFE4E4E7)
val Zinc300 = Color(0xFFD4D4D8)
val Zinc400 = Color(0xFFA1A1AA)
val Zinc500 = Color(0xFF71717A)
val Zinc600 = Color(0xFF52525B)
val Zinc700 = Color(0xFF3F3F46)
val Zinc800 = Color(0xFF27272A)
val Zinc900 = Color(0xFF18181B)
val Zinc950 = Color(0xFF09090B)

private val LightColorScheme =
    lightColorScheme(
        primary = Zinc900,
        onPrimary = Zinc50,
        primaryContainer = Zinc200,
        onPrimaryContainer = Zinc900,
        secondary = Zinc600,
        onSecondary = Zinc50,
        secondaryContainer = Zinc100,
        onSecondaryContainer = Zinc900,
        tertiary = Zinc700,
        onTertiary = Zinc50,
        background = Color.White,
        onBackground = Zinc900,
        surface = Zinc50,
        onSurface = Zinc900,
        surfaceVariant = Zinc100,
        onSurfaceVariant = Zinc700,
        outline = Zinc300,
    )

private val DarkColorScheme =
    darkColorScheme(
        primary = Zinc50,
        onPrimary = Zinc900,
        primaryContainer = Zinc700,
        onPrimaryContainer = Zinc50,
        secondary = Zinc400,
        onSecondary = Zinc900,
        secondaryContainer = Zinc800,
        onSecondaryContainer = Zinc300,
        tertiary = Zinc300,
        onTertiary = Zinc900,
        background = Zinc950,
        onBackground = Zinc50,
        surface = Zinc900,
        onSurface = Zinc50,
        surfaceVariant = Zinc800,
        onSurfaceVariant = Zinc300,
        outline = Zinc700,
    )

@Composable
fun EgoGraphTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme

    CompositionLocalProvider(
        LocalEgoGraphDimens provides EgoGraphDimens(),
        LocalEgoGraphShapes provides EgoGraphShapes(),
        LocalEgoGraphExtendedColors provides EgoGraphExtendedColors(),
    ) {
        MaterialTheme(
            colorScheme = colorScheme,
            content = content,
        )
    }
}
