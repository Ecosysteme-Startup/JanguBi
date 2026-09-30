<#--
  Gabarit des e-mails Jàngu Bi (HTML). Reprend apps/templates/emails/base.html de l'API :
  tableaux de 600 px, styles en ligne (Gmail et Outlook ignorent les feuilles <style>),
  mode sombre et petits écrans en complément pour les clients qui les comprennent.
  emailLayout(title, eyebrow, preheader) ; macros : greeting, p, muted, button, note, signature.
-->
<#assign jbFont = "'Libre Franklin', Arial, Helvetica, sans-serif">
<#assign jbSerif = "'Source Serif 4', Georgia, 'Times New Roman', serif">

<#function jbLogoUrl>
    <#local configured = (properties.logoUrl!'')?trim>
    <#if configured?starts_with("http")><#return configured></#if>
    <#if url?? && (url.resourcesUrl)?? && url.resourcesUrl?has_content><#return url.resourcesUrl + "/img/logo-email.png"></#if>
    <#return "">
</#function>

<#function jbWebUrl>
    <#local configured = (properties.jbWebUrl!'')?trim>
    <#if configured?starts_with("http")><#return configured?remove_ending("/")></#if>
    <#return "">
</#function>

<#macro emailLayout title="" eyebrow="" preheader="">
<#local logo = jbLogoUrl()>
<#local web = jbWebUrl()>
<!DOCTYPE html>
<html lang="${(locale.language)!'fr'}" dir="${(ltr!true)?then('ltr','rtl')}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<meta name="format-detection" content="telephone=no, date=no, address=no, email=no">
<title><#if title?has_content>${title}<#else>${realmName!'Jàngu Bi'}</#if></title>
<link href="https://fonts.googleapis.com/css2?family=Libre+Franklin:wght@400;600&amp;family=Source+Serif+4:opsz,wght@8..60,600&amp;display=swap" rel="stylesheet">
<style>
  @media only screen and (max-width: 620px) {
    .jb-body { padding: 28px 20px 24px !important; }
    .jb-h1 { font-size: 23px !important; line-height: 30px !important; }
  }
  @media (prefers-color-scheme: dark) {
    .jb-page { background-color: #0B1118 !important; }
    .jb-card { background-color: #111A24 !important; border-color: #243142 !important; }
    .jb-body, .jb-h1, .jb-name, .jb-strong { color: #F2F5F8 !important; }
    .jb-muted, .jb-footer, .jb-footer a, .jb-fallback, .jb-signature { color: #92A2B4 !important; }
    .jb-footer-org { color: #BAC6D3 !important; }
    .jb-link { color: #7CC3EE !important; }
    .jb-fallback a { color: #92A2B4 !important; }
    .jb-btn-cell { background-color: #7CC3EE !important; }
    .jb-btn { color: #0B1118 !important; }
    .jb-note { background-color: #13304A !important; }
    .jb-note-cell { color: #D9EBF7 !important; }
    .jb-eyebrow { color: #7CC3EE !important; }
  }
</style>
<!--[if mso]><style>.jb-body, .jb-btn, .jb-footer { font-family: Arial, sans-serif !important; }</style><![endif]-->
</head>
<body class="jb-page" style="margin: 0; padding: 0; width: 100%; background-color: #F7FAFD; -webkit-text-size-adjust: 100%;">
<#if preheader?has_content><div style="display: none; max-height: 0; overflow: hidden; mso-hide: all; font-size: 1px; line-height: 1px; color: #F7FAFD; opacity: 0;">${preheader}&#8199;&#847;&#8199;&#847;&#8199;&#847;&#8199;&#847;&#8199;&#847;&#8199;&#847;</div></#if>
<table role="presentation" class="jb-page" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse: collapse; width: 100%; background-color: #F7FAFD;">
  <tr>
    <td align="center" style="padding: 0 12px;">
      <!--[if mso]><table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse: collapse; width: 100%; max-width: 600px;">
        <tr>
          <td style="padding: 32px 24px 20px; text-align: center;">
            <#if web?has_content><a href="${web}/" style="text-decoration: none;"></#if>
            <#if logo?has_content><img src="${logo}" width="42" height="48" alt="" style="display: inline-block; vertical-align: middle; width: 42px; height: 48px; border: 0; outline: none; text-decoration: none;"></#if>
            <span class="jb-name" style="vertical-align: middle; padding-left: 10px; font-family: ${jbSerif}; font-size: 24px; line-height: 32px; font-weight: 600; color: #0E1A2B; letter-spacing: -0.01em; text-decoration: none;">Jàngu Bi</span>
            <#if web?has_content></a></#if>
          </td>
        </tr>
        <tr>
          <td class="jb-card" style="background-color: #FFFFFF; border: 1px solid #DDE5EE; border-radius: 16px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse: collapse;">
              <tr>
                <td class="jb-body" style="padding: 40px 40px 32px; font-family: ${jbFont}; font-size: 16px; line-height: 24px; color: #0E1A2B; text-align: left;">
                  <#if eyebrow?has_content><p class="jb-eyebrow" style="margin: 0 0 8px; font-size: 13px; line-height: 20px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: #0A6BA3;">${eyebrow}</p></#if>
                  <#if title?has_content><h1 class="jb-h1" style="margin: 0 0 16px; font-family: ${jbSerif}; font-size: 26px; line-height: 34px; font-weight: 600; color: #0E1A2B; letter-spacing: -0.01em;">${title}</h1></#if>
                  <#nested>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        <tr>
          <td class="jb-footer" style="padding: 24px 32px 40px; font-family: ${jbFont}; font-size: 12px; line-height: 19px; color: #586677; text-align: center;">
            <p class="jb-footer-org" style="margin: 0 0 6px; font-weight: 600; color: #3A4859;">${msg("jbFooterDiocese")}</p>
            <p style="margin: 0 0 6px;">${msg("jbFooterTagline")}</p>
            <p style="margin: 0 0 6px;">${msg("jbFooterAuto")}<#if web?has_content> ${msg("jbFooterHelp")} <a href="${web}/pour-les-paroisses#contact" style="color: #586677; text-decoration: underline;">${msg("jbFooterHelpLink")}</a>.</#if></p>
            <p style="margin: 0 0 6px;"><#if web?has_content><a href="${web}/confidentialite" style="color: #586677; text-decoration: underline;">${msg("jbFooterPrivacy")}</a> · </#if>${msg("jbFooterLaw")}</p>
            <p style="margin: 0;">${msg("jbFooterCopyright", .now?string("yyyy"))}</p>
          </td>
        </tr>
      </table>
      <!--[if mso]></td></tr></table><![endif]-->
    </td>
  </tr>
</table>
</body>
</html>
</#macro>

<#-- « Bonjour Awa, » ou « Bonjour, ». -->
<#macro greeting>
<p style="margin: 0 0 16px;"><#if user?? && (user.firstName!'')?has_content>${msg("jbGreeting", user.firstName)}<#else>${msg("jbGreetingAnonymous")}</#if></p>
</#macro>

<#macro p>
<p style="margin: 0 0 16px;"><#nested></p>
</#macro>

<#macro muted>
<p class="jb-muted" style="margin: 0 0 16px; color: #586677; font-size: 14px; line-height: 21px;"><#nested></p>
</#macro>

<#-- Bouton « à l'épreuve des clients mail » et lien en clair dessous. -->
<#macro button href label fallback=true>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border-collapse: collapse; margin: 8px 0 24px;">
  <tr><td class="jb-btn-cell" align="center" style="border-radius: 12px; background-color: #0A6BA3;"><a class="jb-btn" href="${href}" target="_blank" rel="noopener" style="display: inline-block; padding: 14px 28px; font-family: ${jbFont}; font-size: 16px; line-height: 20px; font-weight: 600; color: #FFFFFF; text-decoration: none; border-radius: 12px;">${label}</a></td></tr>
</table>
<#if fallback><p class="jb-fallback" style="margin: 0 0 16px; font-size: 12px; line-height: 18px; color: #586677; word-break: break-all;">${msg("jbFallback")}<br><a href="${href}" style="color: #586677; text-decoration: underline;">${href}</a></p></#if>
</#macro>

<#-- Encadré d'information (bleu clair). -->
<#macro note>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse: collapse; width: 100%; margin: 0 0 20px;">
  <tr><td class="jb-note jb-note-cell" style="padding: 14px 18px; border-radius: 12px; background-color: #EEF6FC; font-size: 14px; line-height: 21px; color: #052F49;"><#nested></td></tr>
</table>
</#macro>

<#macro signature>
<p class="jb-signature" style="margin: 24px 0 0; color: #3A4859;">${msg("jbSignature")}<br>${msg("jbTeam")}</p>
</#macro>
