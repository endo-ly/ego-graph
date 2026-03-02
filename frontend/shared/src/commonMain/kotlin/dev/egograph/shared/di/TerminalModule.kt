package dev.egograph.shared.di

import dev.egograph.shared.core.data.repository.TerminalRepositoryImpl
import dev.egograph.shared.core.data.repository.internal.RepositoryClient
import dev.egograph.shared.core.domain.repository.TerminalRepository
import dev.egograph.shared.core.platform.PlatformPreferences
import dev.egograph.shared.core.platform.PlatformPrefsDefaults
import dev.egograph.shared.core.platform.PlatformPrefsKeys
import dev.egograph.shared.core.platform.getDefaultGatewayBaseUrl
import dev.egograph.shared.core.platform.normalizeBaseUrl
import org.koin.core.qualifier.named
import org.koin.dsl.module

val terminalModule =
    module {
        // === Gateway Configuration ===
        single<String>(qualifier = named("GatewayBaseUrl")) {
            val preferences = getOrNull<PlatformPreferences>()
            val savedUrl = preferences?.getString(PlatformPrefsKeys.KEY_GATEWAY_API_URL, PlatformPrefsDefaults.DEFAULT_GATEWAY_API_URL)
            val rawUrl = if (savedUrl.isNullOrBlank()) getDefaultGatewayBaseUrl() else savedUrl
            try {
                normalizeBaseUrl(rawUrl)
            } catch (e: IllegalArgumentException) {
                getDefaultGatewayBaseUrl()
            }
        }

        // === RepositoryClient (Gateway API) ===
        single<RepositoryClient>(qualifier = named("GatewayClient")) {
            RepositoryClient(
                httpClient = get(),
                baseUrl = get(qualifier = named("GatewayBaseUrl")),
                apiKey = "",
            )
        }

        // === Repository ===
        single<TerminalRepository> {
            TerminalRepositoryImpl(
                repositoryClient = get(qualifier = named("GatewayClient")),
            )
        }
    }
