from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _

# ====================================================================================
# ================================        CUSTOMERS        ===========================
# ====================================================================================


# __MODELS__
class Customers(models.Model):
    customer = models.CharField(max_length=255, null=True, blank=True)  # Name field
    email = models.CharField(
        max_length=255, null=True, blank=True
    )  # Changed from EmailField
    number = models.CharField(max_length=255, null=True, blank=True)  # Phone field
    company = models.CharField(max_length=255, null=True, blank=True)
    dateadded = models.DateTimeField(blank=True, null=True)
    lastvisiteddate = models.DateTimeField(blank=True, null=True)
    rep = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return (
            f"{self.customer} - {self.company}" if self.customer else "Unnamed Customer"
        )

    class Meta:
        db_table = "wfdash_customers"  # Match existing table name
        verbose_name = _("Customers")
        verbose_name_plural = _("Customers")
        managed = False  # Tell Django not to manage table creation/deletion


# ====================================================================================
# ================================        QUOTES        ==============================
# ====================================================================================


class Quoterequest(models.Model):

    # __Quoterequest_FIELDS__
    description = models.TextField(max_length=255, null=True, blank=True)
    status = models.TextField(max_length=255, null=True, blank=True)
    qty = models.IntegerField(null=True, blank=True)
    date = models.DateTimeField(blank=True, null=True, default=timezone.now)
    noteslink = models.TextField(max_length=255, null=True, blank=True)

    # __Quoterequest_FIELDS__END

    class Meta:
        verbose_name = _("Quoterequest")
        verbose_name_plural = _("Quoterequest")


# ====================================================================================
# ================================        SUPPLIERS        ===========================
# ====================================================================================


class Suppliers(models.Model):

    # __Suppliers_FIELDS__
    coordinates = models.TextField(max_length=255, null=True, blank=True)
    closingtime = models.TextField(max_length=255, null=True, blank=True)
    suppliername = models.TextField(max_length=255, null=True, blank=True)
    suppliernumber = models.TextField(max_length=255, null=True, blank=True)
    supplieraddress = models.TextField(max_length=255, null=True, blank=True)
    supply_tags = models.CharField(
        max_length=500,
        null=True,
        blank=True,
        help_text="Enter tags separated by commas (e.g., bolts, nuts, paint)",
    )

    # __Suppliers_FIELDS__END

    class Meta:
        verbose_name = _("Suppliers")
        verbose_name_plural = _("Suppliers")


# ====================================================================================
# ================================        COMPANY        =============================
# ====================================================================================


class Company(models.Model):

    # __Company_FIELDS__
    company = models.TextField(
        max_length=255, null=True, blank=True
    )  # Field name is 'company'
    address = models.TextField(max_length=255, null=True, blank=True)
    vendor = models.CharField(
        max_length=100,
        blank=True,
        help_text="Vendor number for mines or other organizations",
    )

    def __str__(self):
        return self.company

    # __Company_FIELDS__END

    class Meta:
        verbose_name = _("Company")
        verbose_name_plural = _("Company")


class CompanyDetails(models.Model):
    company_name = models.CharField(max_length=100)
    address = models.TextField()
    number = models.CharField(max_length=20)
    email = models.EmailField()
    vat_number = models.CharField(max_length=20, blank=True)
    registration_number = models.CharField(max_length=20, blank=True)
    logo = models.ImageField(upload_to="company_logos/", null=True, blank=True)

    class Meta:
        verbose_name = "Company Details"
        verbose_name_plural = "Company Details"

    def __str__(self):
        return self.company_name


# ====================================================================================
# ================================        ORDERS        ==============================
# ====================================================================================


class Orders(models.Model):

    # __Orders_FIELDS__
    orderdate = models.DateTimeField(blank=True, null=True, default=timezone.now)
    company = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(max_length=255, null=True, blank=True)
    qty = models.IntegerField(null=True, blank=True)
    status = models.TextField(max_length=255, null=True, blank=True)

    # __Orders_FIELDS__END

    class Meta:
        verbose_name = _("Orders")
        verbose_name_plural = _("Orders")


# ====================================================================================
# =============================        DRIVERR LIST        ===========================
# ====================================================================================


class Driverlist(models.Model):

    # __Driverlist_FIELDS__
    qty = models.IntegerField(null=True, blank=True)
    supplier = models.TextField(max_length=255, null=True, blank=True)
    status = models.TextField(max_length=255, null=True, blank=True)
    completeddate = models.DateTimeField(blank=True, null=True, default=timezone.now)

    # __Driverlist_FIELDS__END

    class Meta:
        verbose_name = _("Driverlist")
        verbose_name_plural = _("Driverlist")


# ====================================================================================
# =============================        OTHER MODELS        ===========================
# ====================================================================================


class Settings(models.Model):
    company_name = models.CharField(max_length=255, default="Your Company Name")
    company_address = models.TextField(blank=True, null=True)
    company_phone = models.CharField(max_length=50, blank=True, null=True)
    company_email = models.EmailField(blank=True, null=True)
    delivery_address = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Settings"
        verbose_name_plural = "Settings"

    def __str__(self):
        return self.company_name
