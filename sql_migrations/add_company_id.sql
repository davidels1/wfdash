-- Add company_id column to wfdash_customers table
ALTER TABLE wfdash_customers 
ADD COLUMN company_id integer REFERENCES wfdash_company(id);

-- Update existing records to link with companies (if needed)
UPDATE wfdash_customers 
SET company_id = (
    SELECT id 
    FROM wfdash_company 
    WHERE wfdash_company.company = wfdash_customers.company
    LIMIT 1
);