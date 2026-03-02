package dev.egograph.shared.features.terminal.session

import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import dev.egograph.shared.core.platform.PlatformPreferences
import dev.egograph.shared.core.platform.PlatformPrefsDefaults
import dev.egograph.shared.core.platform.PlatformPrefsKeys
import dev.egograph.shared.core.platform.getDefaultGatewayBaseUrl
import dev.egograph.shared.core.platform.normalizeBaseUrl
import io.ktor.http.encodeURLParameter

/**
 * ターミナル設定データ
 *
 * @property wsUrl WebSocket URL
 * @property error エラーメッセージ
 */
data class TerminalSettings(
    val wsUrl: String?,
    val error: String?,
)

/**
 * ターミナル設定を生成する
 *
 * @param agentId エージェントID
 * @param preferences プラットフォーム設定
 * @return ターミナル設定
 */
@Composable
fun rememberTerminalSettings(
    agentId: String,
    preferences: PlatformPreferences,
): TerminalSettings {
    return remember(agentId, preferences) {
        val gatewayUrl =
            preferences
                .getString(
                    PlatformPrefsKeys.KEY_GATEWAY_API_URL,
                    PlatformPrefsDefaults.DEFAULT_GATEWAY_API_URL,
                ).ifBlank { getDefaultGatewayBaseUrl() }
                .trim()
        if (gatewayUrl.isBlank()) {
            TerminalSettings(
                wsUrl = null,
                error = "Gateway API URL is not configured",
            )
        } else {
            val normalizedUrl =
                try {
                    normalizeBaseUrl(gatewayUrl)
                } catch (_: IllegalArgumentException) {
                    return@remember TerminalSettings(
                        wsUrl = null,
                        error = "Gateway API URL is invalid",
                    )
                }
            val wsBaseUrl =
                when {
                    normalizedUrl.startsWith("https://") -> normalizedUrl.replaceFirst("https://", "wss://")
                    normalizedUrl.startsWith("http://") -> normalizedUrl.replaceFirst("http://", "ws://")
                    else -> normalizedUrl
                }
            TerminalSettings(
                wsUrl = "$wsBaseUrl/api/ws/terminal?session_id=${agentId.encodeURLParameter()}",
                error = null,
            )
        }
    }
}
