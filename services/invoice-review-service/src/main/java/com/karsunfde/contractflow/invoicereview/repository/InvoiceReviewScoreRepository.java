package com.karsunfde.contractflow.invoicereview.repository;

import com.karsunfde.contractflow.invoicereview.model.InvoiceReviewScore;
import org.springframework.data.mongodb.repository.MongoRepository;

import java.util.List;

public interface InvoiceReviewScoreRepository extends MongoRepository<InvoiceReviewScore, String> {
    List<InvoiceReviewScore> findByInvoiceReviewId(String invoiceReviewId);
    List<InvoiceReviewScore> findByInvoiceReviewIdAndProposalId(String invoiceReviewId, String proposalId);
    List<InvoiceReviewScore> findByEvaluatorId(String evaluatorId);
}
