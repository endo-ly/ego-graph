package dev.egograph.android

import android.app.Application
import dev.egograph.android.notifications.NotificationChannelManager
import dev.egograph.shared.di.androidModule
import dev.egograph.shared.di.appModule
import org.koin.android.ext.koin.androidContext
import org.koin.core.context.startKoin

/**
 * EgoGraph Application class
 *
 * Initializes Koin dependency injection container on app startup.
 * Must be declared in AndroidManifest.xml as the application class.
 */
class EgoGraphApplication : Application() {
    /**
     * Application entry point
     *
     * Starts Koin with all application modules before any activity is launched.
     */
    override fun onCreate() {
        super.onCreate()

        // 通知チャンネルを作成（Android 8.0+）
        NotificationChannelManager.createNotificationChannel(this)

        // Initialize Koin DI container
        startKoin {
            androidContext(this@EgoGraphApplication)
            modules(appModule, androidModule)
        }
    }
}
