import logging
from django.core.management.base import BaseCommand
from marketplace.dispatch_service import process_ncm_dispatch_queue

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Drains and processes queued and pending-retry NCM courier dispatch jobs."

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=50,
            help='Maximum number of queued dispatches to process (default: 50).'
        )

    def handle(self, *args, **options):
        limit = options.get('limit', 50)
        self.stdout.write(f"Processing up to {limit} queued/pending-retry NCM dispatches...")
        res = process_ncm_dispatch_queue(limit=limit)
        self.stdout.write(
            self.style.SUCCESS(
                f"Queue processing complete: {res.get('processed', 0)} processed, "
                f"{res.get('succeeded', 0)} succeeded, {res.get('failed', 0)} failed."
            )
        )

