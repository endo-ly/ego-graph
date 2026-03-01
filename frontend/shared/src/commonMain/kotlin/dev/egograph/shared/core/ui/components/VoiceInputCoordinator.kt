package dev.egograph.shared.core.ui.components

import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import dev.egograph.shared.core.platform.terminal.createPermissionUtil
import dev.egograph.shared.core.platform.terminal.createSpeechRecognizer
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * 音声入力のUI状態とトグル操作をまとめたコーディネーター。
 *
 * @property isActive 音声認識が有効かどうか
 * @property onToggle 音声認識の開始/停止を切り替える処理
 */
data class VoiceInputCoordinator(
    val isActive: Boolean,
    val onToggle: () -> Unit,
)

/**
 * 音声入力コーディネーターを生成して Compose ライフサイクルに追従させる。
 *
 * @param onRecognizedText 認識した確定テキストを受け取るコールバック
 * @param onError 音声認識や権限取得で発生したエラーを受け取るコールバック
 */
@Composable
fun rememberVoiceInputCoordinator(
    onRecognizedText: (String) -> Unit,
    onError: (String) -> Unit,
): VoiceInputCoordinator {
    val coroutineScope = rememberCoroutineScope()
    val permissionUtil = remember { createPermissionUtil() }
    val speechRecognizer = remember { createSpeechRecognizer() }

    var voiceInputJob by remember { mutableStateOf<Job?>(null) }
    var isVoiceInputActive by remember { mutableStateOf(false) }
    val voiceInputMutex = remember { Mutex() }

    val stopVoiceInput: () -> Unit = {
        speechRecognizer.stopRecognition()
        voiceInputJob?.cancel()
        voiceInputJob = null
        isVoiceInputActive = false
    }

    val toggleVoiceInput: () -> Unit = {
        if (isVoiceInputActive) {
            stopVoiceInput()
        } else {
            coroutineScope.launch {
                voiceInputMutex.withLock {
                    if (isVoiceInputActive) {
                        return@withLock
                    }

                    val hasPermission =
                        permissionUtil.hasRecordAudioPermission() ||
                            permissionUtil.requestRecordAudioPermission().granted
                    if (!hasPermission) {
                        onError("Microphone permission is required")
                        return@withLock
                    }

                    onError("")
                    isVoiceInputActive = true
                    voiceInputJob?.cancel()
                    voiceInputJob =
                        launch {
                            try {
                                speechRecognizer.startRecognition().collectLatest { recognizedText ->
                                    if (recognizedText.isNotBlank()) {
                                        onRecognizedText(recognizedText)
                                    }
                                }
                            } catch (e: Exception) {
                                onError(e.message ?: "Voice input failed")
                            } finally {
                                isVoiceInputActive = false
                                voiceInputJob = null
                            }
                        }
                }
            }
        }
    }

    DisposableEffect(Unit) {
        onDispose {
            stopVoiceInput()
        }
    }

    return VoiceInputCoordinator(
        isActive = isVoiceInputActive,
        onToggle = toggleVoiceInput,
    )
}
