package dev.egograph.shared.core.platform.voice

import kotlinx.coroutines.flow.Flow

interface ISpeechRecognizer {
    suspend fun startRecognition(): Flow<String>
    fun stopRecognition()
}

expect fun createSpeechRecognizer(): ISpeechRecognizer
