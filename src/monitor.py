import os
import sys
import time
import random
from datetime import date, datetime
from typing import Dict, Any
from curl_cffi import requests
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.discord_utils import ImmoweltDiscordWebhook
from utils.load_proxies import proxies as loaded_proxies
from utils.logging_setter import setup_logger

load_dotenv()

logger = setup_logger('nintendo_monitor', 'nintendo_monitor.log')


def available_dates(calendar_data: dict | None, today: date) -> set[str]:
    """Dates that are on sale, open, and strictly in the future."""
    if not calendar_data:
        return set()
    calendar = calendar_data.get("data", {}).get("calendar", {})
    found = set()
    for date_str, info in calendar.items():
        if info.get("sale_status") != 1 or info.get("open_status") != 1:
            continue
        if datetime.strptime(date_str, "%Y-%m-%d").date() <= today:
            continue
        found.add(date_str)
    return found


class NintendoMuseumMonitor:
    """Monitor for Nintendo Museum ticket availability"""

    def __init__(self):
        self.base_url = "https://museum-tickets.nintendo.com"
        self.api_url = f"{self.base_url}/en/api/calendar"
        self.webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
        self.discord_webhook = NintendoMuseumDiscordWebhook(self.webhook_url)
        self.notified_dates = set()

    def get_random_proxy(self):
        """Get a random proxy from the loaded proxies"""
        if loaded_proxies and len(loaded_proxies) > 0 and loaded_proxies[0]:
            proxy = random.choice(loaded_proxies)
            logger.info(f"Using proxy: {proxy}")
            return proxy
        else:
            logger.info("No proxies available, using direct connection")
            return None

    def fetch_calendar(self, year: int, month: int) -> Dict[str, Any]:
        """Fetch calendar data for a specific month"""
        proxy = self.get_random_proxy()

        headers = {
            'Connection': 'keep-alive',
            'sec-ch-ua-platform': '"macOS"',
            'X-Requested-With': 'XMLHttpRequest',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'sec-ch-ua': '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
            'sec-ch-ua-mobile': '?0',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Referer': f'{self.base_url}/en/calendar',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': 'de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7'
        }

        params = {
            'target_year': year,
            'target_month': month
        }

        try:
            response = requests.get(
                self.api_url,
                params=params,
                headers=headers,
                proxies=proxy,
                impersonate="chrome110",
                timeout=30
            )

            if response.status_code == 200:
                logger.info(f"Successfully fetched calendar for {year}-{month:02d}")
                return response.json()
            else:
                logger.error(f"Failed to fetch calendar: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error fetching calendar: {str(e)}")
            return None

    def check_availability(self, calendar_data: Dict[str, Any]) -> list:
        """Check for dates with sale_status == 1 and open_status == 1"""
        if not calendar_data or 'data' not in calendar_data:
            return []

        calendar = calendar_data.get('data', {}).get('calendar', {})
        available_dates = []
        today = datetime.now().date()

        for date_str, info in calendar.items():
            sale_status = info.get('sale_status')
            open_status = info.get('open_status')

            # Parse date
            date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()

            # Only notify if: tickets available AND museum is open AND date is in future
            if sale_status == 1 and open_status == 1 and date_obj > today and date_str not in self.notified_dates:
                available_dates.append({
                    'date': date_str,
                    'info': info
                })
                logger.info(f"Found available date: {date_str} (sale_status={sale_status}, open_status={open_status})")

        return available_dates

    def send_notification(self, available_dates: list):
        """Send Discord notification for available dates"""
        if not available_dates:
            return

        for date_info in available_dates:
            date = date_info['date']
            info = date_info['info']

            notification_data = {
                'url': f'{self.base_url}/en/calendar',
                'title': f'Nintendo Museum Tickets Available!',
                'description': f'Tickets are available for: **{date}**',
                'thumbnail': f'{self.base_url}/images/logo.svg',
                'fields': [
                    {
                        'name': 'Date',
                        'value': date,
                        'inline': True
                    },
                    {
                        'name': 'Status',
                        'value': 'Available',
                        'inline': True
                    },
                    {
                        'name': 'Link',
                        'value': f'[Book now]({self.base_url}/en/calendar)',
                        'inline': False
                    }
                ]
            }

            if self.send_custom_webhook(notification_data):
                self.notified_dates.add(date)
                logger.info(f"Notification sent for {date}")
            else:
                logger.error(f"Failed to send notification for {date}")

    def send_custom_webhook(self, data: Dict[str, Any]) -> bool:
        """Send custom Discord webhook"""
        from discord_webhook import DiscordWebhook, DiscordEmbed

        if not self.webhook_url:
            logger.error("Discord webhook URL not configured")
            return False

        try:
            webhook = DiscordWebhook(url=self.webhook_url)

            embed = DiscordEmbed(
                title=data.get('title', 'Nintendo Museum Update')[:256],
                description=data.get('description', '')[:4096],
                color='03b2f8'
            )

            if data.get('url'):
                embed.set_url(data['url'])

            if data.get('thumbnail'):
                embed.set_thumbnail(url=data['thumbnail'])

            for field in data.get('fields', []):
                embed.add_embed_field(
                    name=field['name'],
                    value=field['value'],
                    inline=field.get('inline', False)
                )

            embed.set_footer(text="Nintendo Museum Monitor", icon_url=data.get('thumbnail', ''))
            embed.set_timestamp()

            webhook.add_embed(embed)
            response = webhook.execute()

            return response.status_code in [200, 204]

        except Exception as e:
            logger.error(f"Error sending webhook: {str(e)}")
            return False

    def monitor(self, year: int, month: int, interval: int = 20):
        """Monitor calendar continuously"""
        logger.info(f"Starting Nintendo Museum Monitor for {year}-{month:02d}")
        logger.info(f"Checking every {interval} seconds")

        while True:
            try:
                logger.info(f"Checking availability at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

                calendar_data = self.fetch_calendar(year, month)

                if calendar_data:
                    available_dates = self.check_availability(calendar_data)

                    if available_dates:
                        logger.info(f"Found {len(available_dates)} available dates")
                        self.send_notification(available_dates)
                    else:
                        logger.info("No new available dates found")

                logger.info(f"Waiting {interval} seconds before next check...")
                time.sleep(interval)

            except KeyboardInterrupt:
                logger.info("Monitor stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in monitor loop: {str(e)}")
                time.sleep(interval)


class NintendoMuseumDiscordWebhook:
    """Custom Discord webhook for Nintendo Museum notifications"""

    def __init__(self, webhook_url: str = None):
        self.webhook_url = webhook_url or os.getenv('DISCORD_WEBHOOK_URL')
        if not self.webhook_url:
            logger.warning("No Discord webhook URL provided")


def main():
    """Main function"""
    now = datetime.now()
    year = now.year
    month = now.month

    monitor = NintendoMuseumMonitor()

    monitor.monitor(year, month, interval=20)


if __name__ == '__main__':
    main()
