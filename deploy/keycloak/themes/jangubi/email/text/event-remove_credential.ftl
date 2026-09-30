<#ftl output_format="plainText">
<#import "template.ftl" as layout>
<@layout.emailLayout title=msg("jbRemoveCredentialTitle") eyebrow=msg("jbSecurityEyebrow")>
${msg("jbRemoveCredentialIntro", event.date?datetime?string("dd/MM/yyyy"), event.date?datetime?string("HH:mm"), event.ipAddress)}

${msg("jbCredentialAdvice")}
</@layout.emailLayout>
