# ZAP by Checkmarx Scanning Report

ZAP by [Checkmarx](https://checkmarx.com/).


## Summary of Alerts

| Risk Level | Number of Alerts |
| --- | --- |
| High | 0 |
| Medium | 1 |
| Low | 2 |
| Informational | 1 |




## Insights

| Level | Reason | Site | Description | Statistic |
| --- | --- | --- | --- | --- |
| Low | Warning |  | ZAP errors logged - see the zap.log file for details | 6    |
| Low | Warning |  | ZAP warnings logged - see the zap.log file for details | 8    |
| Info | Informational |  | Percentage of network failures | 5 % |
| Info | Informational | http://clients2.google.com | Percentage of responses with status code 2xx | 100 % |
| Info | Informational | http://clients2.google.com | Percentage of endpoints with content type application/json | 100 % |
| Info | Informational | http://clients2.google.com | Percentage of endpoints with method GET | 100 % |
| Info | Informational | http://clients2.google.com | Count of total endpoints | 1    |
| Info | Informational | http://clients2.google.com | Percentage of slow responses | 100 % |
| Info | Informational | https://fonts.googleapis.com | Percentage of responses with status code 2xx | 100 % |
| Info | Informational | https://fonts.googleapis.com | Percentage of slow responses | 100 % |
| Info | Informational | https://localhost | Percentage of responses with status code 2xx | 95 % |
| Info | Informational | https://localhost | Percentage of responses with status code 4xx | 4 % |
| Info | Informational | https://localhost | Percentage of endpoints with content type application/javascript | 20 % |
| Info | Informational | https://localhost | Percentage of endpoints with content type text/css | 20 % |
| Info | Informational | https://localhost | Percentage of endpoints with content type text/html | 40 % |
| Info | Informational | https://localhost | Percentage of endpoints with content type text/plain | 20 % |
| Info | Informational | https://localhost | Percentage of endpoints with method GET | 100 % |
| Info | Informational | https://localhost | Count of total endpoints | 5    |
| Info | Informational | https://placewareaiapp.online | Percentage of responses with status code 2xx | 95 % |
| Info | Informational | https://placewareaiapp.online | Percentage of responses with status code 4xx | 4 % |
| Info | Informational | https://placewareaiapp.online | Percentage of endpoints with content type application/javascript | 20 % |
| Info | Informational | https://placewareaiapp.online | Percentage of endpoints with content type text/css | 20 % |
| Info | Informational | https://placewareaiapp.online | Percentage of endpoints with content type text/html | 40 % |
| Info | Informational | https://placewareaiapp.online | Percentage of endpoints with content type text/plain | 20 % |
| Info | Informational | https://placewareaiapp.online | Percentage of endpoints with method GET | 100 % |
| Info | Informational | https://placewareaiapp.online | Count of total endpoints | 5    |
| Info | Informational | https://placewareaiapp.online | Percentage of slow responses | 46 % |
| Info | Informational | https://unpkg.com | Percentage of responses with status code 2xx | 100 % |
| Info | Informational | https://unpkg.com | Percentage of slow responses | 100 % |







## Alerts

| Name | Risk Level | Number of Instances |
| --- | --- | --- |
| Content Security Policy (CSP) Header Not Set | Medium | 2 |
| Strict-Transport-Security Header Not Set | Low | 2 |
| X-Content-Type-Options Header Missing | Low | 2 |
| Modern Web Application | Informational | 2 |




## Alert Detail



### [ Content Security Policy (CSP) Header Not Set ](https://www.zaproxy.org/docs/alerts/10038/)



##### Medium (High)

### Description

Content Security Policy (CSP) is an added layer of security that helps to detect and mitigate certain types of attacks, including Cross Site Scripting (XSS) and data injection attacks. These attacks are used for everything from data theft to site defacement or distribution of malware. CSP provides a set of standard HTTP headers that allow website owners to declare approved sources of content that browsers should be allowed to load on that page — covered types are JavaScript, CSS, HTML frames, fonts, images and embeddable objects such as Java applets, ActiveX, audio and video files.

* URL: https://placewareaiapp.online/
  * Node Name: `https://placewareaiapp.online/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: ``
  * Other Info: ``
* URL: https://placewareaiapp.online/sitemap.xml
  * Node Name: `https://placewareaiapp.online/sitemap.xml`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: ``
  * Other Info: ``


Instances: 2

### Solution

Ensure that your web server, application server, load balancer, etc. is configured to set the Content-Security-Policy header.

### Reference


* [ https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CSP ](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CSP)
* [ https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html ](https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html)
* [ https://www.w3.org/TR/CSP/ ](https://www.w3.org/TR/CSP/)
* [ https://w3c.github.io/webappsec-csp/ ](https://w3c.github.io/webappsec-csp/)
* [ https://web.dev/articles/csp ](https://web.dev/articles/csp)
* [ https://caniuse.com/#feat=contentsecuritypolicy ](https://caniuse.com/#feat=contentsecuritypolicy)
* [ https://content-security-policy.com/ ](https://content-security-policy.com/)


#### CWE Id: [ 693 ](https://cwe.mitre.org/data/definitions/693.html)


#### WASC Id: 15

#### Source ID: 3

### [ Strict-Transport-Security Header Not Set ](https://www.zaproxy.org/docs/alerts/10035/)



##### Low (High)

### Description

HTTP Strict Transport Security (HSTS) is a web security policy mechanism whereby a web server declares that complying user agents (such as a web browser) are to interact with it using only secure HTTPS connections (i.e. HTTP layered over TLS/SSL). HSTS is an IETF standards track protocol and is specified in RFC 6797.

* URL: https://placewareaiapp.online/assets/index-BVsTa1uv.css
  * Node Name: `https://placewareaiapp.online/assets/index-BVsTa1uv.css`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: ``
  * Other Info: ``
* URL: https://placewareaiapp.online/assets/index-D2IKuT1f.js
  * Node Name: `https://placewareaiapp.online/assets/index-D2IKuT1f.js`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: ``
  * Other Info: ``


Instances: 2

### Solution

Ensure that your web server, application server, load balancer, etc. is configured to enforce Strict-Transport-Security.

### Reference


* [ https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Strict_Transport_Security_Cheat_Sheet.html ](https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Strict_Transport_Security_Cheat_Sheet.html)
* [ https://owasp.org/www-community/Security_Headers ](https://owasp.org/www-community/Security_Headers)
* [ https://en.wikipedia.org/wiki/HTTP_Strict_Transport_Security ](https://en.wikipedia.org/wiki/HTTP_Strict_Transport_Security)
* [ https://caniuse.com/stricttransportsecurity ](https://caniuse.com/stricttransportsecurity)
* [ https://datatracker.ietf.org/doc/html/rfc6797 ](https://datatracker.ietf.org/doc/html/rfc6797)


#### CWE Id: [ 319 ](https://cwe.mitre.org/data/definitions/319.html)


#### WASC Id: 15

#### Source ID: 3

### [ X-Content-Type-Options Header Missing ](https://www.zaproxy.org/docs/alerts/10021/)



##### Low (Medium)

### Description

The Anti-MIME-Sniffing header X-Content-Type-Options was not set to 'nosniff'. This allows older versions of Internet Explorer and Chrome to perform MIME-sniffing on the response body, potentially causing the response body to be interpreted and displayed as a content type other than the declared content type. Current (early 2014) and legacy versions of Firefox will use the declared content type (if one is set), rather than performing MIME-sniffing.

* URL: https://placewareaiapp.online/assets/index-BVsTa1uv.css
  * Node Name: `https://placewareaiapp.online/assets/index-BVsTa1uv.css`
  * Method: `GET`
  * Parameter: `x-content-type-options`
  * Attack: ``
  * Evidence: ``
  * Other Info: `This issue still applies to error type pages (401, 403, 500, etc.) as those pages are often still affected by injection issues, in which case there is still concern for browsers sniffing pages away from their actual content type.
At "High" threshold this scan rule will not alert on client or server error responses.`
* URL: https://placewareaiapp.online/assets/index-D2IKuT1f.js
  * Node Name: `https://placewareaiapp.online/assets/index-D2IKuT1f.js`
  * Method: `GET`
  * Parameter: `x-content-type-options`
  * Attack: ``
  * Evidence: ``
  * Other Info: `This issue still applies to error type pages (401, 403, 500, etc.) as those pages are often still affected by injection issues, in which case there is still concern for browsers sniffing pages away from their actual content type.
At "High" threshold this scan rule will not alert on client or server error responses.`


Instances: 2

### Solution

Ensure that the application/web server sets the Content-Type header appropriately, and that it sets the X-Content-Type-Options header to 'nosniff' for all web pages.
If possible, ensure that the end user uses a standards-compliant and modern web browser that does not perform MIME-sniffing at all, or that can be directed by the web application/web server to not perform MIME-sniffing.

### Reference


* [ https://learn.microsoft.com/en-us/previous-versions/windows/internet-explorer/ie-developer/compatibility/gg622941(v=vs.85) ](https://learn.microsoft.com/en-us/previous-versions/windows/internet-explorer/ie-developer/compatibility/gg622941(v=vs.85))
* [ https://owasp.org/www-community/Security_Headers ](https://owasp.org/www-community/Security_Headers)


#### CWE Id: [ 693 ](https://cwe.mitre.org/data/definitions/693.html)


#### WASC Id: 15

#### Source ID: 3

### [ Modern Web Application ](https://www.zaproxy.org/docs/alerts/10109/)



##### Informational (Medium)

### Description

The application appears to be a modern web application. If you need to explore it automatically then the Client Spider may well be more effective than the standard one.

* URL: https://placewareaiapp.online/
  * Node Name: `https://placewareaiapp.online/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `<script type="module" crossorigin src="/assets/index-D2IKuT1f.js"></script>`
  * Other Info: `No links have been found while there are scripts, which is an indication that this is a modern web application.`
* URL: https://placewareaiapp.online/sitemap.xml
  * Node Name: `https://placewareaiapp.online/sitemap.xml`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `<script type="module" crossorigin src="/assets/index-D2IKuT1f.js"></script>`
  * Other Info: `No links have been found while there are scripts, which is an indication that this is a modern web application.`


Instances: 2

### Solution

This is an informational alert and so no changes are required.

### Reference




#### Source ID: 3


