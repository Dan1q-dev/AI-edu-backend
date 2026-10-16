"""Archive domain objects while retaining their content and student history."""

from collections import defaultdict

from django.core.exceptions import ObjectDoesNotExist
from django.db import models, router, transaction
from django.utils import timezone


class SoftDeleteQuerySet(models.QuerySet):
    def delete(self):
        # Collect first, so validation cannot leave a partially archived tree.
        with transaction.atomic(using=self.db):
            pending = list(self.select_for_update(of=('self',)))
            collected = defaultdict(set)
            while pending:
                instance = pending.pop()
                model = type(instance)
                if instance.deleted_at is not None or instance.pk in collected[model]:
                    continue
                instance.validate_soft_delete()
                collected[model].add(instance.pk)
                pending.extend(instance.soft_delete_related())
            deleted_at = timezone.now()
            counts = {}
            for model, ids in collected.items():
                count = model.all_objects.using(self.db).filter(pk__in=ids, deleted_at__isnull=True).update(
                    deleted_at=deleted_at, **model.soft_delete_updates)
                if count:
                    counts[model._meta.label] = count
            self._result_cache = None
            return sum(counts.values()), counts

    delete.alters_data = True
    delete.queryset_only = True


class SoftDeleteManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class SoftDeleteModel(models.Model):
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True, editable=False)
    objects = SoftDeleteManager()
    # Historical foreign keys must still resolve to archived rows.
    all_objects = SoftDeleteQuerySet.as_manager()
    soft_delete_cascade = ()
    soft_delete_updates = {}

    class Meta:
        abstract = True

    def validate_soft_delete(self):
        pass

    def soft_delete_related(self):
        for name in self.soft_delete_cascade:
            try:
                related = getattr(self, name)
            except ObjectDoesNotExist:
                continue
            if related is None:
                continue
            if isinstance(related, models.Model):
                yield related
            else:
                yield from related.using(self._state.db).select_for_update().all()

    def delete(self, using=None, keep_parents=False):
        if self.pk is None:
            raise ValueError('Cannot delete an object without a primary key')
        using = using or router.db_for_write(type(self), instance=self)
        result = type(self).all_objects.using(using).filter(pk=self.pk).delete()
        self.refresh_from_db(using=using)
        return result

    delete.alters_data = True
