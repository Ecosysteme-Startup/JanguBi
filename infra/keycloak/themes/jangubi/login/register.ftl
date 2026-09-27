<#import "template.ftl" as layout>
<#import "user-profile-commons.ftl" as userProfileCommons>
<#import "register-commons.ftl" as registerCommons>
<#-- WEB-Inscription-Compte : étape 1 sur 3. Les étapes 2 (paroisse) et 3 (consentements) vivent dans l'application
     (/bienvenue). Les champs viennent du profil utilisateur déclaratif (realm-jangubi.json) : prénom, nom, e-mail,
     téléphone (facultatif, indicatif +221) et date de naissance (facultative, sert à vérifier la majorité) sont placés
     comme sur la maquette ; tout autre attribut ajouté au profil est rendu à la suite par user-profile-commons.ftl.
     La confirmation du mot de passe, exigée par Keycloak, est recopiée par jangubi.js (l'œil permet de vérifier la
     saisie, comme sur la maquette) ; sans JavaScript, le champ reste visible. -->
<#assign jbAttrs = {}>
<#list profile.attributes as attribute><#assign jbAttrs = jbAttrs + {attribute.name: attribute}></#list>
<#assign jbPlaced = ["username", "email", "firstName", "lastName", "phone", "birthdate", "locale"]>
<@layout.registrationLayout layout="wide"; section>
    <#if section = "form">
        <ol class="jb-stepper" aria-label="${msg('registerStepsLabel')}">
            <li class="jb-step" aria-current="step"><span class="jb-step-num" aria-hidden="true">1</span><span class="jb-step-text"><span class="jb-sr">${msg("stepCurrentSr")} </span>${msg("registerStep1")}</span></li>
            <li class="jb-step-line" aria-hidden="true"></li>
            <li class="jb-step"><span class="jb-step-num" aria-hidden="true">2</span><span class="jb-step-text"><span class="jb-sr">${msg("stepUpcomingSr")} </span>${msg("registerStep2")}</span></li>
            <li class="jb-step-line" aria-hidden="true"></li>
            <li class="jb-step"><span class="jb-step-num" aria-hidden="true">3</span><span class="jb-step-text"><span class="jb-sr">${msg("stepUpcomingSr")} </span>${msg("registerStep3")}</span></li>
        </ol>

        <div class="jb-register">
            <form id="kc-register-form" class="jb-form" action="${url.registrationAction}" method="post" novalidate>
                <h1 class="jb-h1" id="kc-page-title"><#if messageHeader??>${kcSanitize(msg("${messageHeader}"))?no_esc}<#else>${msg("registerTitle")}</#if></h1>
                <p class="jb-lead">${msg("registerLead")}</p>

                <#if messagesPerField.exists('global') && message?has_content>
                    <@layout.alert type=message.type>${kcSanitize(message.summary)?no_esc}</@layout.alert>
                </#if>

                <#if jbAttrs.firstName?? || jbAttrs.lastName??>
                    <div class="jb-row">
                        <#if jbAttrs.firstName??><@textField attribute=jbAttrs.firstName autocomplete="given-name"/></#if>
                        <#if jbAttrs.lastName??><@textField attribute=jbAttrs.lastName autocomplete="family-name"/></#if>
                    </div>
                </#if>

                <#if jbAttrs.email??>
                    <@textField attribute=jbAttrs.email type="email" autocomplete="email" validMark=true help=msg("emailHelp")/>
                </#if>
                <#if jbAttrs.username?? && !realm.registrationEmailAsUsername>
                    <@textField attribute=jbAttrs.username autocomplete="username"/>
                </#if>

                <#if jbAttrs.phone?? || jbAttrs.birthdate??>
                    <div class="jb-row">
                        <#if jbAttrs.phone??><@phoneField attribute=jbAttrs.phone/></#if>
                        <#if jbAttrs.birthdate??><@dateField attribute=jbAttrs.birthdate/></#if>
                    </div>
                    <#if jbAttrs.birthdate??>
                        <div class="jb-note" id="jb-birthdate-note">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
                            <span>${msg("birthdateNote")}</span>
                        </div>
                    </#if>
                </#if>

                <#-- Attributs du profil non placés par la maquette : rendu générique. -->
                <@userProfileCommons.userProfileFormFields skip=jbPlaced/>

                <#if passwordRequired??>
                    <div class="jb-field">
                        <label for="password" class="jb-label">${msg("password")}</label>
                        <div class="jb-control jb-has-eye" dir="ltr">
                            <input type="password" id="password" name="password" class="jb-input" autocomplete="new-password" data-jb-strength
                                   aria-describedby="jb-pw-rules<#if messagesPerField.existsError('password')> input-error-password</#if>"
                                   <#if messagesPerField.existsError('password','password-confirm')>aria-invalid="true"</#if>/>
                            <@layout.eye target="password"/>
                        </div>
                        <#if messagesPerField.existsError('password')>
                            <@layout.fieldError id="input-error-password">${kcSanitize(messagesPerField.get('password'))?no_esc}</@layout.fieldError>
                        </#if>
                        <div class="jb-strength" data-level="0">
                            <div class="jb-bars" aria-hidden="true"><span></span><span></span><span></span><span></span></div>
                            <span class="jb-strength-label" aria-live="polite" data-jb-strength-label
                                  data-weak="${msg('pwWeak')}" data-fair="${msg('pwFair')}" data-strong="${msg('pwStrong')}" data-prefix="${msg('pwStrength')}"></span>
                        </div>
                        <ul class="jb-rules" id="jb-pw-rules" aria-label="${msg('pwRulesTitle')}">
                            <#list ["length", "case", "digit"] as rule>
                                <li data-rule="${rule}">
                                    <svg class="jb-rule-todo" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="8"/></svg>
                                    <svg class="jb-rule-ok" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>
                                    ${msg("pwRule_" + rule)}
                                </li>
                            </#list>
                        </ul>
                    </div>
                    <div class="jb-field" data-jb-confirm>
                        <label for="password-confirm" class="jb-label">${msg("passwordConfirm")}</label>
                        <div class="jb-control jb-has-eye" dir="ltr">
                            <input type="password" id="password-confirm" name="password-confirm" class="jb-input" autocomplete="new-password"
                                   <#if messagesPerField.existsError('password-confirm')>aria-invalid="true" aria-describedby="input-error-password-confirm"</#if>/>
                            <@layout.eye target="password-confirm"/>
                        </div>
                        <#if messagesPerField.existsError('password-confirm')>
                            <@layout.fieldError id="input-error-password-confirm">${kcSanitize(messagesPerField.get('password-confirm'))?no_esc}</@layout.fieldError>
                        </#if>
                    </div>
                </#if>

                <#if termsAcceptanceRequired??><div class="jb-terms"><@registerCommons.termsAcceptance/></div></#if>

                <#if recaptchaRequired?? && (recaptchaVisible!false)>
                    <div class="jb-field"><div class="g-recaptcha" data-size="compact" data-sitekey="${recaptchaSiteKey}" data-action="${recaptchaAction}"></div></div>
                </#if>

                <button class="jb-btn jb-btn-primary jb-btn-block" type="submit">${msg("registerContinue")}<span class="jb-sr"> ${msg("registerContinueSr")}</span></button>
            </form>

            <aside class="jb-panel" aria-labelledby="jb-benefits-title">
                <h2 class="jb-h2" id="jb-benefits-title">${msg("registerPanelTitle")}</h2>
                <ul class="jb-benefits">
                    <li>
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 9h4"/><path d="M12 7v5"/><path d="M14 22v-4a2 2 0 0 0-4 0v4"/><path d="M18 22V5.618a1 1 0 0 0-.553-.894l-4.553-2.277a2 2 0 0 0-1.788 0L6.553 4.724A1 1 0 0 0 6 5.618V22"/><path d="m18 7 3.447 1.724a1 1 0 0 1 .553.894V20a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-10.382a1 1 0 0 1 .553-.894L6 7"/></svg>
                        <div><span class="jb-benefit-title">${msg("benefitParishTitle")}</span><span class="jb-benefit-text">${msg("benefitParishText")}</span></div>
                    </li>
                    <li>
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/></svg>
                        <div><span class="jb-benefit-title">${msg("benefitActTitle")}</span><span class="jb-benefit-text">${msg("benefitActText")}</span></div>
                    </li>
                    <li>
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/></svg>
                        <div><span class="jb-benefit-title">${msg("benefitPriestTitle")}</span><span class="jb-benefit-text">${msg("benefitPriestText")}</span></div>
                    </li>
                    <li>
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2v4"/><path d="M16 2v4"/><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M3 10h18"/></svg>
                        <div><span class="jb-benefit-title">${msg("benefitConfessionTitle")}</span><span class="jb-benefit-text">${msg("benefitConfessionText")}</span></div>
                    </li>
                </ul>
                <div class="jb-data">
                    <h3 class="jb-data-title"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/></svg>${msg("dataTitle")}</h3>
                    <p>${msg("dataText")}</p>
                    <a class="jb-hit" href="${properties.jbWebUrl!}/confidentialite">${msg("dataLink")}</a>
                </div>
            </aside>
        </div>
        <script type="module" src="${url.resourcesPath}/js/passwordVisibility.js"></script>
    </#if>
</@layout.registrationLayout>

<#-- Attributs ARIA d'un champ du profil : obligatoire, erreur et aides reliées. -->
<#macro aria attribute extra=[]>
    <#assign describedBy = extra>
    <#if messagesPerField.existsError(attribute.name)><#assign describedBy = describedBy + ["input-error-" + attribute.name]></#if>
    <#if messagesPerField.existsError(attribute.name)>aria-invalid="true"</#if>
    <#if describedBy?has_content>aria-describedby="${describedBy?join(' ')}"</#if>
    <#if attribute.required>aria-required="true"</#if>
    <#if attribute.readOnly>disabled</#if>
</#macro>

<#macro errorOf attribute>
    <#if messagesPerField.existsError(attribute.name)>
        <@layout.fieldError id="input-error-${attribute.name}">${kcSanitize(messagesPerField.get(attribute.name))?no_esc}</@layout.fieldError>
    </#if>
</#macro>

<#macro textField attribute type="text" autocomplete="" validMark=false help="">
    <div class="jb-field">
        <label for="${attribute.name}" class="jb-label">${advancedMsg(attribute.displayName!'')}</label>
        <div class="jb-control<#if validMark> jb-has-icon</#if>"<#if validMark> data-jb-valid</#if>>
            <input type="${type}" id="${attribute.name}" name="${attribute.name}" value="${(attribute.value!'')}" class="jb-input"
                   <#if autocomplete?has_content>autocomplete="${autocomplete}"</#if>
                   <#if type == "email">inputmode="email" dir="ltr"</#if>
                   <#if attribute.annotations.inputTypeMaxlength??>maxlength="${attribute.annotations.inputTypeMaxlength}"</#if>
                   <@aria attribute=attribute extra=help?has_content?then(["help-" + attribute.name], [])/>/>
            <#if validMark>
                <svg class="jb-input-icon jb-input-icon-ok jb-valid-mark" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" role="img" aria-label="${msg('validAddress')}"><path d="M20 6 9 17l-5-5"/></svg>
            </#if>
        </div>
        <@errorOf attribute=attribute/>
        <#if help?has_content><div class="jb-help" id="help-${attribute.name}">${help}</div></#if>
    </div>
</#macro>

<#macro phoneField attribute>
    <#assign phoneErr = messagesPerField.existsError(attribute.name)>
    <div class="jb-field">
        <div class="jb-label-row">
            <label for="${attribute.name}" class="jb-label">${advancedMsg(attribute.displayName!'')}</label>
            <#if !attribute.required><span class="jb-optional" id="optional-${attribute.name}">${msg("optional")}</span></#if>
        </div>
        <div class="jb-phone<#if phoneErr> is-invalid</#if>" dir="ltr">
            <span class="jb-phone-prefix" id="prefix-${attribute.name}"><#if attribute.annotations.inputHelperTextBefore??>${advancedMsg(attribute.annotations.inputHelperTextBefore)}<#else>+221</#if></span>
            <input type="tel" id="${attribute.name}" name="${attribute.name}" value="${(attribute.value!'')}" autocomplete="tel-national" inputmode="tel"
                   <#if attribute.annotations.inputTypePlaceholder??>placeholder="${advancedMsg(attribute.annotations.inputTypePlaceholder)}"</#if>
                   <#if attribute.annotations.inputTypeMaxlength??>maxlength="${attribute.annotations.inputTypeMaxlength}"</#if>
                   <@aria attribute=attribute extra=["prefix-" + attribute.name] + (!attribute.required)?then(["optional-" + attribute.name], [])/>/>
        </div>
        <@errorOf attribute=attribute/>
    </div>
</#macro>

<#macro dateField attribute>
    <div class="jb-field">
        <div class="jb-label-row">
            <label for="${attribute.name}" class="jb-label">${advancedMsg(attribute.displayName!'')}</label>
        </div>
        <div class="jb-control jb-has-icon">
            <input type="date" id="${attribute.name}" name="${attribute.name}" value="${(attribute.value!'')}" class="jb-input jb-date jb-tnum<#if !(attribute.value?has_content)> jb-date-empty</#if>"
                   autocomplete="bday" min="1900-01-01" max="${.now?string('yyyy-MM-dd')}" data-jb-date
                   <@aria attribute=attribute extra=["help-" + attribute.name, "jb-birthdate-note"]/>/>
            <svg class="jb-input-icon jb-input-icon-muted" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2v4"/><path d="M16 2v4"/><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M3 10h18"/></svg>
        </div>
        <@errorOf attribute=attribute/>
        <div class="jb-help" id="help-${attribute.name}">${msg("birthdateHelp")}</div>
    </div>
</#macro>
