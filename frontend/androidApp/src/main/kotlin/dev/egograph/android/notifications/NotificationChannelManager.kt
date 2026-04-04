package dev.egograph.android.notifications

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import androidx.core.content.getSystemService

/**
 * Android 13+ (API 33+) で必須の通知チャンネル管理
 *
 * Android 8.0 (API 26) 以降、通知にはチャンネル登録が必要です。
 * Android 13 (API 33) 以降、POST_NOTIFICATIONSパーミッションも必要です。
 */
object NotificationChannelManager {
    private const val CHANNEL_ID = "egograph_notifications"
    private const val CHANNEL_NAME = "EgoGraph Notifications"
    private const val CHANNEL_DESCRIPTION = "General app notifications"

    /**
     * 通知チャンネルを作成する
     *
     * Android 8.0以上で実行され、まだチャンネルが存在しない場合のみ作成されます。
     *
     * @param context アプリケーションコンテキスト
     */
    fun createNotificationChannel(context: Context) {
        // Android 8.0 (API 26) 以上でチャンネル作成が必要
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel =
                NotificationChannel(
                    CHANNEL_ID,
                    CHANNEL_NAME,
                    NotificationManager.IMPORTANCE_DEFAULT,
                ).apply {
                    description = CHANNEL_DESCRIPTION
                    enableVibration(true)
                    setShowBadge(true)
                }

            val notificationManager = context.getSystemService<NotificationManager>()
            notificationManager?.createNotificationChannel(channel)
        }
    }

    /**
     * 通知チャンネルIDを取得する
     *
     * @return 通知チャンネルID
     */
    fun getChannelId(): String = CHANNEL_ID
}
