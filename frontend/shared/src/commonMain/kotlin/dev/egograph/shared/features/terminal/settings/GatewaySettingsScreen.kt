package dev.egograph.shared.features.terminal.settings

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import cafe.adriel.voyager.core.screen.Screen
import cafe.adriel.voyager.koin.koinScreenModel
import dev.egograph.shared.core.platform.isValidUrl
import dev.egograph.shared.core.ui.components.SecretTextField
import dev.egograph.shared.core.ui.components.SettingsTopBar
import dev.egograph.shared.core.ui.theme.EgoGraphThemeTokens
import kotlinx.coroutines.launch

/**
 * Gateway設定画面
 *
 * Gateway APIのURLとAPIキーを設定する画面。
 *
 * @param onBack 戻るボタンコールバック
 */
class GatewaySettingsScreen(
    private val onBack: () -> Unit = {},
) : Screen {
    @Composable
    override fun Content() {
        val screenModel = koinScreenModel<GatewaySettingsScreenModel>()
        val state by screenModel.state.collectAsState()
        val snackbarHostState = remember { SnackbarHostState() }

        LaunchedEffect(Unit) {
            screenModel.effect.collect { effect ->
                when (effect) {
                    is GatewaySettingsEffect.ShowMessage -> launch { snackbarHostState.showSnackbar(effect.message) }
                    GatewaySettingsEffect.NavigateBack -> onBack()
                }
            }
        }

        Scaffold(
            snackbarHost = { SnackbarHost(snackbarHostState) },
            topBar = {
                SettingsTopBar(title = "Gateway Settings", onBack = onBack)
            },
        ) { paddingValues ->
            Surface(
                modifier =
                    Modifier
                        .fillMaxSize()
                        .padding(paddingValues),
            ) {
                GatewaySettingsContent(
                    gatewayUrl = state.inputGatewayUrl,
                    onGatewayUrlChange = screenModel::onGatewayUrlChange,
                    apiKey = state.inputApiKey,
                    onApiKeyChange = screenModel::onApiKeyChange,
                    onSave = screenModel::saveSettings,
                    isSaving = state.isSaving,
                )
            }
        }
    }
}

@Composable
private fun GatewaySettingsContent(
    gatewayUrl: String,
    onGatewayUrlChange: (String) -> Unit,
    apiKey: String,
    onApiKeyChange: (String) -> Unit,
    onSave: () -> Unit,
    isSaving: Boolean,
) {
    val dimens = EgoGraphThemeTokens.dimens

    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .padding(dimens.space16),
    ) {
        Text(
            text = "Gateway API Configuration",
            style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.padding(bottom = dimens.space8),
        )

        OutlinedTextField(
            value = gatewayUrl,
            onValueChange = onGatewayUrlChange,
            label = { Text("Gateway API URL") },
            placeholder = { Text("http://100.x.x.x:8001") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            isError = gatewayUrl.isNotBlank() && !isValidUrl(gatewayUrl),
            supportingText = {
                Text(
                    text = "Example: http://100.x.x.x:8001",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            },
        )

        Spacer(modifier = Modifier.height(dimens.space16))

        SecretTextField(
            value = apiKey,
            onValueChange = onApiKeyChange,
            label = "Gateway API Key",
            placeholder = "Required",
            modifier = Modifier.fillMaxWidth(),
            showContentDescription = "Show token",
            hideContentDescription = "Hide token",
        )

        Spacer(modifier = Modifier.height(dimens.space16))

        Button(
            onClick = onSave,
            modifier = Modifier.fillMaxWidth(),
            enabled = !isSaving && isValidUrl(gatewayUrl) && apiKey.isNotBlank(),
        ) {
            Text("Save Gateway Settings")
        }
    }
}
