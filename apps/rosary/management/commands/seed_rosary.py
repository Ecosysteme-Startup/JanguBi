import json
import logging
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.rosary.models import Mystery, MysteryGroup, MysteryPrayer, Prayer, RosaryDay

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Seed Rosary data from init JSON file"

    def _ensure_rosary_bucket(self) -> None:
        endpoint_url = getattr(settings, 'AWS_S3_ENDPOINT_URL', None)
        if not endpoint_url:
            return  # local storage, nothing to create

        import boto3
        from botocore.exceptions import ClientError

        s3 = boto3.client(
            's3',
            endpoint_url=endpoint_url,
            aws_access_key_id=getattr(settings, 'AWS_S3_ACCESS_KEY_ID', None),
            aws_secret_access_key=getattr(settings, 'AWS_S3_SECRET_ACCESS_KEY', None),
            region_name=getattr(settings, 'AWS_S3_REGION_NAME', 'us-east-1'),
        )
        bucket = 'rosary-audio'
        try:
            s3.head_bucket(Bucket=bucket)
        except ClientError as exc:
            code = exc.response['Error']['Code']
            if code in ('404', 'NoSuchBucket', '403'):
                s3.create_bucket(Bucket=bucket)
                try:
                    s3.put_bucket_acl(Bucket=bucket, ACL='public-read')
                except ClientError:
                    pass  # ACL not supported by all MinIO versions
                self.stdout.write(self.style.SUCCESS(f"Created bucket: {bucket}"))
            else:
                raise

    def handle(self, *args, **options):
        self._ensure_rosary_bucket()
        # We look for the file in the expected path
        json_path = Path(settings.BASE_DIR) / "init" / "rosary" / "format" / "json" / "rosary_french.json"
        
        if not json_path.exists():
            self.stdout.write(self.style.ERROR(f"File not found: {json_path}"))
            return

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Mappings for days
        day_mapping = {
            "lundi": 0,
            "mardi": 1,
            "mercredi": 2,
            "jeudi": 3,
            "vendredi": 4,
            "samedi": 5,
            "dimanche": 6,
        }

        # Prayer types dict for mapping fields to choices
        prayer_type_map = {
            "our_father": Prayer.Type.OUR_FATHER,
            "hail_mary": Prayer.Type.HAIL_MARY,
            "glory_be": Prayer.Type.GLORY_BE,
            "fatima_prayer": Prayer.Type.FATIMA,
            "creed": Prayer.Type.CREED,
            "holy_queen": Prayer.Type.HOLY_QUEEN,
            "final_prayer": Prayer.Type.FINAL_PRAYER,
            "sign_of_cross_start": Prayer.Type.SIGN_OF_CROSS,
            "sign_of_cross_end": Prayer.Type.SIGN_OF_CROSS,
        }

        with transaction.atomic():
            self.stdout.write("Starting Rosary Data import...")

            for day_key, day_data in data.items():
                if day_key == "_instructions":
                    continue
                    
                group_name = day_data["group"]
                
                # 1. Create or get Mystery Group
                group, group_created = MysteryGroup.objects.get_or_create(
                    name=group_name,
                    defaults={"slug": group_name.lower()}
                )
                
                # Check for audio file
                if group_created or not group.audio_file:
                    audio_filename = f"Mystères {group_name}.mp3"
                    audio_path = Path(settings.BASE_DIR) / "init" / "rosary" / "format" / "mp3" / audio_filename
                    if audio_path.exists():
                        from django.core.files import File
                        with open(audio_path, "rb") as f:
                            group.audio_file.save(audio_filename, File(f), save=True)
                        self.stdout.write(self.style.SUCCESS(f"Uploaded audio for group {group_name}"))
                        
                        # Clean up the local file after uploading
                        # audio_path.unlink()
                        # self.stdout.write(self.style.SUCCESS(f"Deleted local audio file: {audio_filename}"))

                # 2. Create or update RosaryDay
                weekday = day_mapping.get(day_key.lower())
                if weekday is not None:
                    RosaryDay.objects.update_or_create(
                        weekday=weekday,
                        defaults={"group": group}
                    )

                # 3. Process Mysteries
                mysteries_data = day_data.get("mysteries", [])
                for m_data in mysteries_data:
                    order = m_data["order"]
                    title = m_data["title"]
                    meditation = m_data.get("meditation", "")
                    fruit = m_data.get("fruit", "")

                    mystery, created = Mystery.objects.update_or_create(
                        group=group,
                        order=order,
                        defaults={"title": title, "meditation": meditation, "fruit": fruit}
                    )

                    if not created:
                        continue # Already processed related prayers

                    # Sequence of prayers for this mystery
                    seq_order = 1
                    
                    # A. Our Father
                    of_text = m_data.get("our_father")
                    if of_text:
                        prayer_obj, _ = Prayer.objects.get_or_create(
                            text=of_text.strip(),
                            language="fr",
                            defaults={"type": prayer_type_map["our_father"]}
                        )
                        MysteryPrayer.objects.create(
                            mystery=mystery, prayer=prayer_obj, order=seq_order
                        )
                        seq_order += 1

                    # B. Hail Marys (usually an array of 10)
                    hm_texts = m_data.get("hail_mary", [])
                    for hm_text in hm_texts:
                        prayer_obj, _ = Prayer.objects.get_or_create(
                            text=hm_text.strip(),
                            language="fr",
                            defaults={"type": prayer_type_map["hail_mary"]}
                        )
                        MysteryPrayer.objects.create(
                            mystery=mystery, prayer=prayer_obj, order=seq_order
                        )
                        seq_order += 1

                    # C. Glory Be
                    gb_text = m_data.get("glory_be")
                    if gb_text:
                        prayer_obj, _ = Prayer.objects.get_or_create(
                            text=gb_text.strip(),
                            language="fr",
                            defaults={"type": prayer_type_map["glory_be"]}
                        )
                        MysteryPrayer.objects.create(
                            mystery=mystery, prayer=prayer_obj, order=seq_order
                        )
                        seq_order += 1

                    # D. Fatima Prayer
                    fatima_text = m_data.get("fatima_prayer")
                    if fatima_text:
                        prayer_obj, _ = Prayer.objects.get_or_create(
                            text=fatima_text.strip(),
                            language="fr",
                            defaults={"type": prayer_type_map["fatima_prayer"]}
                        )
                        MysteryPrayer.objects.create(
                            mystery=mystery, prayer=prayer_obj, order=seq_order
                        )
                        seq_order += 1

                    self.stdout.write(f"    - Processed Mystery: {title}")

                # 4. Intro and Closing prayers (Standalone, for client retrieval)
                intro_data = day_data.get("intro", {})
                for p_key, p_val in intro_data.items():
                    if not p_val:
                        continue
                    # Handle hail_mary which is a list in intro
                    texts = p_val if isinstance(p_val, list) else [p_val]
                    for t in texts:
                        try:
                            Prayer.objects.get_or_create(
                                text=t.strip(),
                                language="fr",
                                defaults={"type": prayer_type_map.get(p_key, Prayer.Type.OTHER)}
                            )
                        except Exception as e:
                            logger.error(f"Failed to create intro prayer {p_key}: {e}")
                
                closing_data = day_data.get("closing", {})
                for p_key, p_val in closing_data.items():
                    if not p_val:
                        continue
                    Prayer.objects.get_or_create(
                        text=p_val.strip(),
                        language="fr",
                        defaults={"type": prayer_type_map.get(p_key, Prayer.Type.OTHER)}
                    )

            self.stdout.write(self.style.SUCCESS("Successfully seeded Rosary data!"))
