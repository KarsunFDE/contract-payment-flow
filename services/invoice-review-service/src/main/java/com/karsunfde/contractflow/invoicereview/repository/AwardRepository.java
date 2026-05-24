package com.karsunfde.contractflow.invoicereview.repository;

import com.karsunfde.contractflow.invoicereview.model.Award;
import org.springframework.data.mongodb.repository.MongoRepository;

import java.util.List;
import java.util.Optional;

public interface AwardRepository extends MongoRepository<Award, String> {
    Optional<Award> findByInvoiceReviewId(String invoiceReviewId);
    /** ⚠ Item 10 — declared but unused. */
    List<Award> findByAgencyId(String agencyId);
}
