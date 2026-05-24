package com.karsunfde.contractflow.invoicereview.repository;

import com.karsunfde.contractflow.invoicereview.model.Deliverable;
import org.springframework.data.mongodb.repository.MongoRepository;

import java.util.List;

public interface DeliverableRepository extends MongoRepository<Deliverable, String> {
    List<Deliverable> findByContractId(String contractId);
}
