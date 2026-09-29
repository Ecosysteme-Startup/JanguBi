<#import "footer.ftl" as loginFooter>
<#--
  Gabarit Jàngu Bi, maquettes « Ciel produit ».
  layout="card" (défaut) : logotype centré, carte de 440 px, note sous la carte, pied de page (WEB-Connexion).
     Sections : header, form, info (pied de carte), below (sous la carte), socialProviders.
  layout="wide" : en-tête, contenu libre sur 1200 px, pied de page (WEB-Inscription-Compte).
     Section : form (la page gère titre, messages et panneau).
-->
<#macro registrationLayout bodyClass="" displayInfo=false displayMessage=true displayRequiredFields=false layout="card" subtitle="">
<#assign jbYear = .now?string("yyyy")>
<!DOCTYPE html>
<html class="${properties.kcHtmlClass!}" lang="${lang}">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="robots" content="noindex, nofollow">
    <meta name="color-scheme" content="light dark">
    <title>${msg("loginTitle",(realm.displayName!''))}</title>
    <link rel="preload" href="${url.resourcesPath}/fonts/libre-franklin-latin.woff2" as="font" type="font/woff2" crossorigin>
    <#if properties.styles?has_content>
        <#list properties.styles?split(' ') as style>
            <link href="${url.resourcesPath}/${style}" rel="stylesheet" />
        </#list>
    </#if>
    <#if properties.scripts?has_content>
        <#list properties.scripts?split(' ') as script>
            <script src="${url.resourcesPath}/${script}" defer></script>
        </#list>
    </#if>
    <script type="importmap">{ "imports": { "rfc4648": "${url.resourcesCommonPath}/vendor/rfc4648/rfc4648.js" } }</script>
    <#if scripts??>
        <#list scripts as script>
            <script src="${script}" type="text/javascript"></script>
        </#list>
    </#if>
    <script type="module">
        import { startSessionPolling } from "${url.resourcesPath}/js/authChecker.js";
        startSessionPolling("${url.ssoLoginInOtherTabsUrl?no_esc}");
    </script>
    <#if authenticationSession??>
        <script type="module">
            import { checkAuthSession } from "${url.resourcesPath}/js/authChecker.js";
            checkAuthSession("${authenticationSession.authSessionIdHash}");
        </script>
    </#if>
</head>
<body class="${properties.kcBodyClass!} <#if layout == 'wide'>jb-wide</#if> ${bodyClass}" data-page-id="login-${pageId}">
<a class="jb-skip" href="#jb-main">${msg("skipToForm")}</a>

<#if layout == "wide">
    <header class="jb-header">
        <div class="jb-header-inner">
            <@logo small=true/>
            <div class="jb-header-aside">
                <span class="jb-header-question">${msg("alreadyRegistered")}</span>
                <a class="jb-btn jb-btn-outline jb-btn-sm jb-hit" href="${url.loginUrl}">${msg("backToLogin")}</a>
            </div>
        </div>
    </header>
    <main class="jb-main-wide" id="jb-main">
        <#nested "form">
    </main>
    <footer class="jb-footer">
        <div class="jb-footer-inner">
            <span>© ${jbYear} Numerisen, Dakar · ${msg("footerLaw")}</span>
            <@footerLinks lang=false/>
        </div>
    </footer>
<#else>
    <@logo small=false/>

    <main class="jb-card" id="jb-main">
        <h1 class="jb-title" id="kc-page-title"><#nested "header"></h1>
        <#if subtitle?has_content><p class="jb-subtitle">${subtitle}</p></#if>
        <#if auth?has_content && auth.showUsername() && !auth.showResetCredentials()>
            <p class="jb-attempted">
                <span id="kc-attempted-username">${auth.attemptedUsername}</span>
                <a id="reset-login" class="jb-hit" href="${url.loginRestartFlowUrl}">${msg("restartLoginTooltip")}</a>
            </p>
        </#if>

        <#if displayMessage && message?has_content && (message.type != 'warning' || !isAppInitiatedAction??)>
            <@alert type=message.type>${kcSanitize(message.summary)?no_esc}</@alert>
        </#if>

        <#nested "form">

        <#if auth?has_content && auth.showTryAnotherWayLink()>
            <div class="jb-card-foot">
                <form id="kc-select-try-another-way-form" action="${url.loginAction}" method="post">
                    <input type="hidden" name="tryAnotherWay" value="on"/>
                    <button type="submit" class="jb-link-button jb-hit">${msg("doTryAnotherWay")}</button>
                </form>
            </div>
        </#if>

        <#nested "socialProviders">

        <#if displayInfo>
            <div id="kc-info" class="jb-card-foot"><#nested "info"></div>
        </#if>
    </main>

    <#nested "below">

    <div class="jb-spacer" aria-hidden="true"></div>
    <footer class="jb-footer">
        <div class="jb-footer-inner">
            <span>© ${jbYear} Numerisen, Dakar</span>
            <@footerLinks lang=true/>
        </div>
    </footer>
</#if>
<@loginFooter.content/>
</body>
</html>
</#macro>

<#-- Logotype : pictogramme livre ouvert (lucide « book-open ») et « Jàngu Bi » en Source Serif 4. -->
<#macro logo small>
    <a class="jb-logo jb-hit <#if small>jb-logo-sm<#else>jb-logo-center</#if>" href="${properties.jbWebUrl!}/" aria-label="${msg('logoLabel')}">
        <span class="jb-logo-mark"><svg width="<#if small>18<#else>22</#if>" height="<#if small>18<#else>22</#if>" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/></svg></span>
        <span class="jb-logo-name">Jàngu Bi</span>
    </a>
</#macro>

<#macro footerLinks lang>
    <nav class="jb-footer-links" aria-label="${msg('footerNav')}">
        <a class="jb-hit" href="${properties.jbWebUrl!}/confidentialite">${msg("privacy")}</a>
        <a class="jb-hit" href="${properties.jbWebUrl!}/conditions">${msg("terms")}</a>
        <a class="jb-hit" href="${properties.jbWebUrl!}/pour-les-paroisses#contact">${msg("help")}</a>
        <#if lang>
            <span class="jb-footer-lang"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/></svg>Français</span>
        </#if>
    </nav>
</#macro>

<#-- Alerte du design system (info, succès, attention, erreur). -->
<#macro alert type>
    <div class="jb-alert jb-alert-${type}" role="<#if type == 'error' || type == 'warning'>alert<#else>status</#if>">
        <#if type == "success">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>
        <#elseif type == "warning">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>
        <#elseif type == "error">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/></svg>
        <#else>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
        </#if>
        <span><#nested></span>
    </div>
</#macro>

<#-- Message d'erreur d'un champ, relié par son id. -->
<#macro fieldError id>
    <div id="${id}" class="jb-error" aria-live="polite"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/></svg><span><#nested></span></div>
</#macro>

<#-- Bouton « œil » du champ mot de passe (passwordVisibility.js du thème base). -->
<#macro eye target>
    <button class="jb-eye" type="button" aria-label="${msg('showPassword')}" aria-controls="${target}" data-password-toggle
            data-icon-show="jb-eye-show" data-icon-hide="jb-eye-hide"
            data-label-show="${msg('showPassword')}" data-label-hide="${msg('hidePassword')}">
        <i class="jb-eye-show" aria-hidden="true"></i>
    </button>
</#macro>

<#-- Champ mot de passe complet (libellé, œil, erreur). -->
<#macro passwordField name label autocomplete invalid=false autofocus=false errorName="">
    <#local err = errorName?has_content?then(errorName, name)>
    <div class="jb-field">
        <label for="${name}" class="jb-label">${label}</label>
        <div class="jb-control jb-has-eye" dir="ltr">
            <input type="password" id="${name}" name="${name}" class="jb-input" autocomplete="${autocomplete}" <#if autofocus>autofocus</#if>
                   <#if invalid>aria-invalid="true"</#if><#if messagesPerField.existsError(err)> aria-describedby="input-error-${err}"</#if>/>
            <@eye target=name/>
        </div>
        <#if messagesPerField.existsError(err)>
            <@fieldError id="input-error-${err}">${kcSanitize(messagesPerField.get(err))?no_esc}</@fieldError>
        </#if>
    </div>
</#macro>
