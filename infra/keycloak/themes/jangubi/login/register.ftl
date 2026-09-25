<#import "template.ftl" as layout>
<#import "user-profile-commons.ftl" as userProfileCommons>
<#import "register-commons.ftl" as registerCommons>
<#-- PUB-Inscription-Compte : étape 1 sur 3 (compte). Les étapes 2 et 3 vivent dans l'application (/bienvenue). -->
<@layout.registrationLayout displayMessage=messagesPerField.exists('global') displayRequiredFields=true aside="register"; section>
    <#if section = "stepper">
        <ol class="jb-stepper" aria-label="Étapes de l'inscription">
            <li class="is-current" aria-current="step"><span>01 · ${msg("stepCurrent")}</span><strong>${msg("registerStep1")}</strong></li>
            <li><span>02 · ${msg("stepUpcoming")}</span>${msg("registerStep2")}</li>
            <li><span>03 · ${msg("stepUpcoming")}</span>${msg("registerStep3")}</li>
        </ol>
        <p class="jb-eyebrow jb-eyebrow-spaced">${msg("registerEyebrow")}</p>
    <#elseif section = "header">
        <#if messageHeader??>${kcSanitize(msg("${messageHeader}"))?no_esc}<#else>${msg("registerTitle")}</#if>
    <#elseif section = "form">
        <form id="kc-register-form" class="jb-form jb-form-register" action="${url.registrationAction}" method="post" novalidate>
            <@userProfileCommons.userProfileFormFields; callback, attribute>
                <#if callback = "afterField">
                    <#if passwordRequired?? && (attribute.name == 'username' || (attribute.name == 'email' && realm.registrationEmailAsUsername))>
                        <div class="jb-group jb-span-2">
                            <label for="password" class="jb-label">${msg("password")} <span class="jb-req" aria-hidden="true">*</span></label>
                            <div class="jb-input-group" dir="ltr">
                                <input type="password" id="password" class="jb-input" name="password" autocomplete="new-password"
                                       aria-describedby="jb-pw-rules<#if messagesPerField.existsError('password')> input-error-password</#if>"
                                       <#if messagesPerField.existsError('password','password-confirm')>aria-invalid="true"</#if> data-jb-strength/>
                                <button class="jb-eye" type="button" aria-label="${msg('showPassword')}" aria-controls="password" data-password-toggle
                                        data-icon-show="jb-eye-show" data-icon-hide="jb-eye-hide"
                                        data-label-show="${msg('showPassword')}" data-label-hide="${msg('hidePassword')}">
                                    <i class="jb-eye-show" aria-hidden="true"></i>
                                </button>
                            </div>
                            <div class="jb-strength" aria-hidden="true"><span></span><span></span><span></span><span></span></div>
                            <p class="jb-hint jb-strength-label" aria-live="polite" data-jb-strength-label
                               data-weak="${msg('pwWeak')}" data-fair="${msg('pwFair')}" data-strong="${msg('pwStrong')}" data-prefix="${msg('pwStrength')}"></p>
                            <ul class="jb-rules" id="jb-pw-rules" aria-label="${msg('pwRulesTitle')}">
                                <li data-rule="length">${msg("pwRuleLength")}</li>
                                <li data-rule="case">${msg("pwRuleCase")}</li>
                                <li data-rule="digit">${msg("pwRuleDigit")}</li>
                                <li data-rule="symbol">${msg("pwRuleSymbol")}</li>
                            </ul>
                            <#if messagesPerField.existsError('password')>
                                <span id="input-error-password" class="jb-error" aria-live="polite">${kcSanitize(messagesPerField.get('password'))?no_esc}</span>
                            </#if>
                        </div>
                        <div class="jb-group jb-span-2">
                            <label for="password-confirm" class="jb-label">${msg("passwordConfirm")} <span class="jb-req" aria-hidden="true">*</span></label>
                            <div class="jb-input-group" dir="ltr">
                                <input type="password" id="password-confirm" class="jb-input" name="password-confirm" autocomplete="new-password"
                                       <#if messagesPerField.existsError('password-confirm')>aria-invalid="true" aria-describedby="input-error-password-confirm"</#if>/>
                                <button class="jb-eye" type="button" aria-label="${msg('showPassword')}" aria-controls="password-confirm" data-password-toggle
                                        data-icon-show="jb-eye-show" data-icon-hide="jb-eye-hide"
                                        data-label-show="${msg('showPassword')}" data-label-hide="${msg('hidePassword')}">
                                    <i class="jb-eye-show" aria-hidden="true"></i>
                                </button>
                            </div>
                            <#if messagesPerField.existsError('password-confirm')>
                                <span id="input-error-password-confirm" class="jb-error" aria-live="polite">${kcSanitize(messagesPerField.get('password-confirm'))?no_esc}</span>
                            </#if>
                        </div>
                    </#if>
                </#if>
            </@userProfileCommons.userProfileFormFields>

            <@registerCommons.termsAcceptance/>

            <div class="jb-actions jb-span-2">
                <a class="jb-btn jb-btn-tertiary" href="${properties.jbWebUrl!}/">${msg("registerCancel")}</a>
                <button class="jb-btn jb-btn-primary jb-btn-lg" type="submit">
                    ${msg("registerContinue")}
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4.5 12h15M13.5 6l6 6-6 6"/></svg>
                </button>
            </div>
        </form>
        <script type="module" src="${url.resourcesPath}/js/passwordVisibility.js"></script>
    </#if>
</@layout.registrationLayout>
