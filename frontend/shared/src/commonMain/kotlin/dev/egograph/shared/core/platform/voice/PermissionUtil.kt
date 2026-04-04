package dev.egograph.shared.core.platform.voice

data class PermissionResult(
    val granted: Boolean,
)

interface PermissionUtil {
    suspend fun requestRecordAudioPermission(): PermissionResult

    fun hasRecordAudioPermission(): Boolean
}

expect fun createPermissionUtil(): PermissionUtil
