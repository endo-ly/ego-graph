package dev.egograph.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import cafe.adriel.voyager.navigator.CurrentScreen
import cafe.adriel.voyager.navigator.Navigator
import dev.egograph.shared.core.platform.voice.ActivityRecorder
import dev.egograph.shared.core.settings.AppTheme
import dev.egograph.shared.core.settings.ThemeRepository
import dev.egograph.shared.core.ui.theme.EgoGraphTheme
import dev.egograph.shared.features.sidebar.SidebarScreen
import org.koin.compose.KoinContext
import org.koin.compose.koinInject

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)

        ActivityRecorder.currentActivity = this

        lifecycle.addObserver(
            LifecycleEventObserver { _, event ->
                if (event == Lifecycle.Event.ON_DESTROY) {
                    ActivityRecorder.currentActivity = null
                }
            },
        )

        setContent {
            KoinContext {
                val themeRepository = koinInject<ThemeRepository>()
                val theme by themeRepository.theme.collectAsState()

                val darkTheme =
                    when (theme) {
                        AppTheme.LIGHT -> false
                        AppTheme.DARK -> true
                        AppTheme.SYSTEM -> isSystemInDarkTheme()
                    }

                EgoGraphTheme(darkTheme = darkTheme) {
                    Navigator(SidebarScreen()) {
                        CurrentScreen()
                    }
                }
            }
        }
    }
}
