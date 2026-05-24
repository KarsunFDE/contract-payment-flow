package com.karsunfde.contractflow.invoicereview.repository;

import com.karsunfde.contractflow.invoicereview.model.InvoiceReview;
import org.springframework.data.mongodb.repository.MongoRepository;

import java.util.List;

public interface InvoiceReviewRepository extends MongoRepository<InvoiceReview, String> {
    List<InvoiceReview> findByContractModificationId(String contract_modificationId);
    /** ⚠ Item 10 — declared but list endpoints often skip. */
    List<InvoiceReview> findByAgencyId(String agencyId);
}
