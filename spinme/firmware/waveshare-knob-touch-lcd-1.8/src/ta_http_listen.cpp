/* Http actor device glue: WiFiServer :80 -> ta_net_http_handle_request.
 * Hidden behind ta_http_wifi_up() / ta_http_listen_start_task().
 * Own FreeRTOS task so draw/player work cannot starve accept().
 * Do not tear the server down on brief WiFi.status() blips.
 */
#include <WiFi.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "ta_net_http_event.h"

extern "C" void ta_http_listen_start_task(void);

static WiFiServer g_srv(80);
static int g_begun;
static int g_task_up;
static uint32_t g_down_since_ms; /* 0 = currently look connected */

static int parse_content_length(const uint8_t *buf, size_t n, size_t *out_len) {
  const char *text;
  const char *cl;
  size_t i;

  *out_len = 0;
  text = (const char *)buf;
  for (i = 0; i + 15 < n; i++) {
    if (strncasecmp(text + i, "Content-Length:", 15) == 0) {
      cl = text + i + 15;
      while (*cl == ' ' || *cl == '\t') {
        cl++;
      }
      *out_len = (size_t)atoi(cl);
      return 0;
    }
  }
  return 0;
}

static int read_request(WiFiClient &cli, uint8_t **out_buf, size_t *out_len) {
  static const size_t kMax = 64u * 1024u;
  uint8_t *buf;
  size_t n = 0;
  size_t cap = 2048;
  size_t hdr_end = 0;
  size_t body_len = 0;
  uint32_t t0 = millis();

  buf = (uint8_t *)malloc(cap);
  if (buf == nullptr) {
    return -1;
  }
  while (millis() - t0 < 3000u) {
    while (cli.available() > 0) {
      int c = cli.read();
      if (c < 0) {
        break;
      }
      if (n + 1 >= cap) {
        size_t ncap = cap * 2;
        uint8_t *nb;
        if (ncap > kMax) {
          free(buf);
          return -1;
        }
        nb = (uint8_t *)realloc(buf, ncap);
        if (nb == nullptr) {
          free(buf);
          return -1;
        }
        buf = nb;
        cap = ncap;
      }
      buf[n++] = (uint8_t)c;
      if (hdr_end == 0 && n >= 4 && buf[n - 4] == '\r' && buf[n - 3] == '\n' &&
          buf[n - 2] == '\r' && buf[n - 1] == '\n') {
        hdr_end = n;
        (void)parse_content_length(buf, hdr_end, &body_len);
        if (body_len > kMax - hdr_end) {
          free(buf);
          return -1;
        }
      }
      if (hdr_end != 0 && n >= hdr_end + body_len) {
        *out_buf = buf;
        *out_len = n;
        return 0;
      }
    }
    if (!cli.connected() && cli.available() == 0) {
      break;
    }
    delay(1);
  }
  free(buf);
  return -1;
}

static void write_response(WiFiClient &cli, const ta_net_http_response_t *resp) {
  char hdr[128];
  size_t blen;
  const uint8_t *bytes;
  int n;

  if (resp == nullptr) {
    return;
  }
  if (resp->blob != nullptr && resp->blob_len > 0) {
    bytes = resp->blob;
    blen = resp->blob_len;
  } else {
    bytes = (const uint8_t *)resp->body;
    blen = resp->body_len;
  }
  n = snprintf(hdr, sizeof(hdr),
               "HTTP/1.0 %d \r\nContent-Length: %u\r\nConnection: close\r\n\r\n",
               resp->http_status, (unsigned)blen);
  if (n > 0) {
    cli.write((const uint8_t *)hdr, (size_t)n);
  }
  if (blen > 0 && bytes != nullptr) {
    cli.write(bytes, blen);
  }
  cli.flush();
}

static void listen_begin(void) {
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }
  if (g_begun) {
    return;
  }
  WiFi.setSleep(false);
  g_srv.begin();
  g_begun = 1;
  g_down_since_ms = 0;
  Serial.println("http :80 listen");
}

static void maybe_recover_wifi(void) {
  const uint32_t now = millis();

  if (WiFi.status() == WL_CONNECTED) {
    g_down_since_ms = 0;
    if (!g_begun) {
      listen_begin();
    }
    return;
  }
  if (g_down_since_ms == 0) {
    g_down_since_ms = now ? now : 1u;
    return;
  }
  if ((now - g_down_since_ms) < 5000u) {
    return;
  }
  if (g_begun) {
    g_srv.end();
    g_begun = 0;
    Serial.println("http :80 stop (wifi down)");
  }
}

static int listen_poll(void) {
  WiFiClient cli;
  uint8_t *req = nullptr;
  size_t req_len = 0;
  ta_net_http_response_t resp;

  maybe_recover_wifi();
  if (!g_begun) {
    return 0;
  }
  cli = g_srv.available();
  if (!cli) {
    return 0;
  }
  cli.setNoDelay(true);
  memset(&resp, 0, sizeof(resp));
  if (read_request(cli, &req, &req_len) != 0 || req == nullptr) {
    cli.stop();
    free(req);
    return -1;
  }
  (void)ta_net_http_handle_request(req, req_len, &resp);
  free(req);
  write_response(cli, &resp);
  free(resp.blob);
  resp.blob = nullptr;
  cli.stop();
  return 1;
}

static void http_listen_task(void *arg) {
  (void)arg;
  Serial.println("http listen task up");
  for (;;) {
    (void)listen_poll();
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}

extern "C" void ta_http_listen_start_task(void) {
  if (g_task_up) {
    return;
  }
  listen_begin();
  BaseType_t ok = xTaskCreatePinnedToCore(http_listen_task, "ta_http", 8192,
                                          nullptr, 2, nullptr, 0);
  if (ok == pdPASS) {
    g_task_up = 1;
  } else {
    Serial.println("http listen task fail");
  }
}
