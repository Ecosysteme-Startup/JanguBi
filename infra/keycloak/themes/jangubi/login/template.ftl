<#import "footer.ftl" as loginFooter>
<#--
  Gabarit Jàngu Bi : bandeau liturgique, panneau éditorial « nuit », colonne du formulaire.
  `aside` choisit le panneau : "word" (connexion, défaut) ou "register" (inscription).
-->
<#macro registrationLayout bodyClass="" displayInfo=false displayMessage=true displayRequiredFields=false aside="word" eyebrow="" subtitle="">
<!DOCTYPE html>
<html class="${properties.kcHtmlClass!}" lang="${lang}">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="robots" content="noindex, nofollow">
    <meta name="color-scheme" content="light dark">
    <title>${msg("loginTitle",(realm.displayName!''))}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Libre+Franklin:ital,wght@0,400;0,500;0,600;1,400&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&display=swap" rel="stylesheet">
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
<body class="${properties.kcBodyClass!} ${bodyClass}" data-page-id="login-${pageId}" data-api-url="${properties.jbApiUrl!}">
<a class="jb-skip" href="#jb-main">Aller au formulaire</a>

<#-- Bandeau liturgique : date locale, puis calendrier du jour si l'API répond (jangubi.js). -->
<div class="jb-banner" id="jb-banner">
    <span class="jb-banner-date"><span data-jb-date></span><span class="jb-muted" data-jb-daynum></span></span>
    <span class="jb-banner-day" data-jb-celebration hidden></span>
    <a class="jb-banner-link" href="${properties.jbWebUrl!}/parole" data-jb-refs>${msg("wordOfDay")}</a>
</div>

<div class="jb-layout <#if aside == 'register'>jb-layout-register</#if>">
    <aside class="jb-aside" aria-label="Jàngu Bi">
        <svg class="jb-arch" viewBox="0 0 600 860" aria-hidden="true" preserveAspectRatio="xMidYMax slice">
            <path d="M120 860V420a180 180 0 0 1 360 0v440" fill="none" stroke="currentColor" stroke-width="1.5"/>
            <path d="M150 860V420a150 150 0 0 1 300 0v440" fill="none" stroke="currentColor" stroke-width="1"/>
            <path d="M300 240v620" stroke="currentColor" stroke-width="1"/>
        </svg>
        <a class="jb-aside-brand" href="${properties.jbWebUrl!}/" aria-label="Jàngu Bi, page d'accueil">
            <span class="jb-brand-name">Jàngu Bi</span><span class="jb-brand-tag">${msg("brandTagline")}</span>
        </a>
        <#if aside == "register">
            <div class="jb-aside-body">
                <p class="jb-aside-eyebrow">Psaume 118 (119), 105</p>
                <blockquote class="jb-quote jb-quote-sm">« Ta parole est une lampe à mes pieds, une lumière sur mon sentier. »</blockquote>
                <ul class="jb-benefits">
                    <li>${msg("registerBenefit1")}</li>
                    <li>${msg("registerBenefit2")}</li>
                    <li>${msg("registerBenefit3")}</li>
                </ul>
            </div>
            <p class="jb-aside-foot">${msg("alreadyRegistered")} <a href="${url.loginUrl}">${msg("backToLogin")}</a></p>
        <#else>
            <figure class="jb-aside-body">
                <p class="jb-aside-eyebrow">Psaume 89 (90), 12</p>
                <blockquote class="jb-quote">« Enseigne-nous à bien compter nos jours, afin que nous appliquions notre cœur à la sagesse. »</blockquote>
                <figcaption class="jb-aside-caption">Traduction Louis Segond</figcaption>
            </figure>
            <div class="jb-aside-foot jb-aside-rule">
                <a href="${properties.jbWebUrl!}/parole">${msg("readWord")}</a><span>${msg("motto")}</span>
            </div>
        </#if>
    </aside>

    <main class="jb-main" id="jb-main">
        <div class="jb-column">
            <#if eyebrow?has_content><p class="jb-eyebrow">${eyebrow}</p></#if>
            <#nested "stepper">
            <#if !(auth?has_content && auth.showUsername() && !auth.showResetCredentials())>
                <h1 class="jb-title" id="kc-page-title"><#nested "header"></h1>
            <#else>
                <h1 class="jb-title" id="kc-page-title"><#nested "header"></h1>
                <p class="jb-attempted">
                    <span id="kc-attempted-username">${auth.attemptedUsername}</span>
                    <a id="reset-login" href="${url.loginRestartFlowUrl}">${msg("restartLoginTooltip")}</a>
                </p>
            </#if>
            <#if subtitle?has_content><p class="jb-subtitle">${subtitle}</p></#if>
            <#if displayRequiredFields><p class="jb-required-note"><span class="jb-req" aria-hidden="true">*</span> ${msg("requiredFields")}</p></#if>

            <#if displayMessage && message?has_content && (message.type != 'warning' || !isAppInitiatedAction??)>
                <div class="jb-alert jb-alert-${message.type}" role="<#if message.type = 'error'>alert<#else>status</#if>">
                    <span class="jb-alert-title">${kcSanitize(message.summary)?no_esc}</span>
                </div>
            </#if>

            <#nested "form">

            <#if auth?has_content && auth.showTryAnotherWayLink()>
                <form id="kc-select-try-another-way-form" action="${url.loginAction}" method="post" class="jb-try-another">
                    <input type="hidden" name="tryAnotherWay" value="on"/>
                    <button type="submit" class="jb-link-button">${msg("doTryAnotherWay")}</button>
                </form>
            </#if>

            <#nested "socialProviders">

            <#if displayInfo>
                <div id="kc-info" class="jb-info"><#nested "info"></div>
            </#if>
        </div>

        <footer class="jb-footer">
            <span class="jb-secure">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="10.5" width="14" height="10" rx="1"/><path d="M8 10.5v-3a4 4 0 0 1 8 0v3"/></svg>
                ${msg("secureFooter")}
            </span>
            <span><a href="${properties.jbWebUrl!}/pour-les-paroisses#contact">${msg("help")}</a> · <a href="${properties.jbWebUrl!}/confidentialite">${msg("privacy")}</a></span>
        </footer>
    </main>
</div>
<@loginFooter.content/>
</body>
</html>
</#macro>
