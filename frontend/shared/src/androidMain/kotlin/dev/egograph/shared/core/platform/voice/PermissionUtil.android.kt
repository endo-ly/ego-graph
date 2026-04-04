package dev.egograph.shared.core.platform.voice

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

actual fun createPermissionUtil(): PermissionUtil =
    object : PermissionUtil {
        override suspend fun requestRecordAudioPermission(): PermissionResult =
            suspendCancellableCoroutine { continuation ->
                val activity =
                    ActivityRecorder.currentActivity as? ComponentActivity
                        ?: run {
                            continuation.resume(PermissionResult(granted = false))
                            return@suspendCancellableCoroutine
                        }

                val launcher =
                    activity.activityResultRegistry.register(
                        "record_audio_permission",
                        ActivityResultContracts.RequestPermission(),
                    ) { isGranted ->
                        if (continuation.isActive) {
                            continuation.resume(PermissionResult(granted = isGranted))
                        }
                    }

                launcher.launch(Manifest.permission.RECORD_AUDIO)

                continuation.invokeOnCancellation {
                    launcher.unregister()
                }
            }

        override fun hasRecordAudioPermission(): Boolean {
            val context = ActivityRecorder.currentActivity ?: return false
            return ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.RECORD_AUDIO,
            ) == PackageManager.PERMISSION_GRANTED
        }
    }

object ActivityRecorder {
    var currentActivity: android.content.Context? = null
}
