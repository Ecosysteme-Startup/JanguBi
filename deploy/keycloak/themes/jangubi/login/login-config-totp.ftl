<#import "template.ftl" as layout>
<#import "password-commons.ftl" as passwordCommons>
<#-- Activation de la double vérification (personnel) : étapes numérotées, QR code ou clé, code et nom d'appareil. -->
<@layout.registrationLayout displayMessage=!messagesPerField.existsError('totp','userLabel') subtitle=msg("loginTotpSubtitle"); section>
    <#if section = "header">
        ${msg("loginTotpTitle")}
    <#elseif section = "form">
        <ol class="jb-steps" id="kc-totp-settings">
            <li>
                <div>
                    <p>${msg("loginTotpStep1")}</p>
                    <ul class="jb-apps" id="kc-totp-supported-apps">
                        <#list totp.supportedApplications as app><li>${msg(app)}</li></#list>
                    </ul>
                </div>
            </li>
            <#if mode?? && mode = "manual">
                <li>
                    <div>
                        <p>${msg("loginTotpManualStep2")}</p>
                        <code class="jb-secret" id="kc-totp-secret-key">${totp.totpSecretEncoded}</code>
                        <a class="jb-hit" href="${totp.qrUrl}" id="mode-barcode">${msg("loginTotpScanBarcode")}</a>
                        <p>${msg("loginTotpManualStep3")}</p>
                        <ul class="jb-kv">
                            <li id="kc-totp-type">${msg("loginTotpType")} : ${msg("loginTotp." + totp.policy.type)}</li>
                            <li id="kc-totp-algorithm">${msg("loginTotpAlgorithm")} : ${totp.policy.getAlgorithmKey()}</li>
                            <li id="kc-totp-digits">${msg("loginTotpDigits")} : ${totp.policy.digits}</li>
                            <#if totp.policy.type = "totp">
                                <li id="kc-totp-period">${msg("loginTotpInterval")} : ${totp.policy.period}</li>
                            <#elseif totp.policy.type = "hotp">
                                <li id="kc-totp-counter">${msg("loginTotpCounter")} : ${totp.policy.initialCounter}</li>
                            </#if>
                        </ul>
                    </div>
                </li>
            <#else>
                <li>
                    <div>
                        <p>${msg("loginTotpStep2")}</p>
                        <span class="jb-qr"><img id="kc-totp-secret-qr-code" src="data:image/png;base64, ${totp.totpSecretQrCode}" alt="${msg('loginTotpQrAlt')}" width="180" height="180"></span><br>
                        <a class="jb-hit" href="${totp.manualUrl}" id="mode-manual">${msg("loginTotpUnableToScan")}</a>
                    </div>
                </li>
            </#if>
            <li><div><p>${msg("loginTotpStep3")}</p></div></li>
        </ol>

        <form action="${url.loginAction}" class="jb-form" id="kc-totp-settings-form" method="post" novalidate>
            <div class="jb-field">
                <label for="totp" class="jb-label">${msg("authenticatorCode")}</label>
                <input type="text" id="totp" name="totp" autocomplete="one-time-code" inputmode="numeric" maxlength="6" class="jb-input jb-input-otp" dir="ltr"
                       <#if messagesPerField.existsError('totp')>aria-invalid="true" aria-describedby="input-error-otp-code"</#if>/>
                <#if messagesPerField.existsError('totp')>
                    <@layout.fieldError id="input-error-otp-code">${kcSanitize(messagesPerField.get('totp'))?no_esc}</@layout.fieldError>
                </#if>
                <input type="hidden" id="totpSecret" name="totpSecret" value="${totp.totpSecret}" />
                <#if mode??><input type="hidden" id="mode" name="mode" value="${mode}"/></#if>
            </div>

            <div class="jb-field">
                <div class="jb-label-row">
                    <label for="userLabel" class="jb-label">${msg("loginTotpDeviceName")}</label>
                    <#if !(totp.otpCredentials?size gte 1)><span class="jb-optional">${msg("optional")}</span></#if>
                </div>
                <input type="text" class="jb-input" id="userLabel" name="userLabel" autocomplete="off" placeholder="${msg('loginTotpDeviceNamePlaceholder')}" style="margin-top:8px"
                       <#if totp.otpCredentials?size gte 1>aria-required="true"</#if>
                       <#if messagesPerField.existsError('userLabel')>aria-invalid="true" aria-describedby="input-error-otp-label"</#if>/>
                <#if messagesPerField.existsError('userLabel')>
                    <@layout.fieldError id="input-error-otp-label">${kcSanitize(messagesPerField.get('userLabel'))?no_esc}</@layout.fieldError>
                </#if>
            </div>

            <label class="jb-check">
                <input type="checkbox" id="logout-sessions" name="logout-sessions" value="on">
                <span class="jb-box" aria-hidden="true"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg></span>
                ${msg("logoutOtherSessions")}
            </label>

            <div class="jb-actions">
                <button type="submit" class="jb-btn jb-btn-primary jb-btn-block" id="saveTOTPBtn">${msg("doSave")}</button>
                <#if isAppInitiatedAction??>
                    <button type="submit" class="jb-btn jb-btn-outline jb-btn-block" id="cancelTOTPBtn" name="cancel-aia" value="true">${msg("doCancel")}</button>
                </#if>
            </div>
        </form>
    </#if>
</@layout.registrationLayout>
