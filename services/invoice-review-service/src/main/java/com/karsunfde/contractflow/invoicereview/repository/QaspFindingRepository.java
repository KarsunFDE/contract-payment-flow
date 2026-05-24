package com.karsunfde.contractflow.invoicereview.repository;

import com.karsunfde.contractflow.invoicereview.model.QaspFinding;
import org.springframework.data.mongodb.repository.MongoRepository;

import java.util.List;

public interface QaspFindingRepository extends MongoRepository<QaspFinding, String> {
    List<QaspFinding> findByContractId(String contractId);
}
